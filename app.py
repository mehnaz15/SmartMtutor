import os
import io
import re
import json
import hashlib
from difflib import SequenceMatcher
from datetime import datetime

import streamlit as st
import pymupdf
import pytesseract
from PIL import Image
from google import genai
import re
from collections import defaultdict
from difflib import SequenceMatcher


def normalize_question(text):
    """Normalize question text for comparison."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return " ".join(text.split())


def get_keywords(text):
    """Extract meaningful words from a question."""
    stop_words = {
        "the", "is", "are", "was", "were", "a", "an", "and",
        "or", "of", "to", "in", "on", "for", "with", "by",
        "what", "why", "how", "explain", "describe", "write",
        "draw", "give", "discuss", "define", "derive", "from"
    }

    words = normalize_question(text).split()
    return {word for word in words if len(word) > 2 and word not in stop_words}


def compare_questions(question1, question2):
    """Return a similarity score between 0 and 1."""
    q1 = normalize_question(question1)
    q2 = normalize_question(question2)

    if not q1 or not q2:
        return 0.0

    if q1 == q2:
        return 1.0

    words1 = get_keywords(q1)
    words2 = get_keywords(q2)

    if not words1 or not words2:
        return SequenceMatcher(None, q1, q2).ratio()

    keyword_similarity = (
        len(words1 & words2) / len(words1 | words2)
    )

    text_similarity = SequenceMatcher(None, q1, q2).ratio()

    return max(keyword_similarity, text_similarity)


def find_repeated_questions(questions, threshold=0.55):
    """
    questions: list of dictionaries containing:
        question, paper, page

    Returns groups of similar questions.
    """
    groups = []

    for item in questions:
        question = item.get("question", "").strip()

        if not question:
            continue

        matched_group = None

        for group in groups:
            score = compare_questions(
                question,
                group["items"][0]["question"]
            )

            if score >= threshold:
                matched_group = group
                break

        if matched_group:
            matched_group["items"].append(item)
        else:
            groups.append({
                "representative": question,
                "items": [item]
            })

    return sorted(
        groups,
        key=lambda group: len(group["items"]),
        reverse=True
    )


# =========================================================
# PAGE CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="SmartMtutor",
    page_icon="📚",
    layout="wide"
)

st.markdown("""
<style>
.main {
    background-color: #f7f8fc;
}
h1, h2, h3 {
    color: #243b64;
}
.stButton > button {
    background-color: #244c86;
    color: white;
    border-radius: 8px;
    border: 1px solid #244c86;
    min-height: 40px;
}
.stButton > button:hover {
    background-color: #18365f;
    color: white;
}
.stButton > button:disabled {
    background-color: #d9e2ef;
    color: #333333;
}
</style>
""", unsafe_allow_html=True)


# =========================================================
# CONFIGURATION
# =========================================================

MODEL_NAME = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.5-flash-lite"
)

TESSERACT_PATH = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

if os.path.exists(TESSERACT_PATH):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH


@st.cache_resource
def get_gemini_client():
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        return None

    return genai.Client(api_key=api_key)


# =========================================================
# SESSION STATE
# =========================================================

DEFAULTS = {
    "course_docs": {},
    "pyq_docs": {},
    "selected_ranges": {},
    "chat_history": [],
    "faq_counter": {},
    "topic_mastery": {},
    "topic_attempts": {},
    "quiz_history": [],
    "quiz_questions": [],
    "quiz_answers": {},
    "quiz_submitted": False,
    "quiz_results": [],
    "studied_pages": set(),
    "pyq_results": [],
    "displayed_pages": {},
    "course_topics": [],
    "faq_question_to_ask": ""
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value


# =========================================================
# TEXT UTILITIES
# =========================================================

def clean_text(text):
    if not text:
        return ""

    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def make_document_id(name, data):
    raw = name.encode("utf-8") + data[:10000] + str(len(data)).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def get_documents(category):
    if category == "course":
        return st.session_state.course_docs

    return st.session_state.pyq_docs


# =========================================================
# FAST PDF UPLOAD
# Upload stores the PDF and reads its page count only.
# No full-document OCR during upload.
# =========================================================

def add_uploaded_documents(files, category):
    documents = get_documents(category)

    for uploaded_file in files:
        data = uploaded_file.getvalue()
        name = uploaded_file.name

        doc_id = make_document_id(name, data)

        if doc_id in documents:
            continue

        try:
            with pymupdf.open(
                stream=data,
                filetype="pdf"
            ) as pdf:
                page_count = len(pdf)

            documents[doc_id] = {
                "id": doc_id,
                "name": name,
                "data": data,
                "page_count": page_count,
                "text_cache": {},
                "ocr_used": False,
                "ocr_errors": {}
            }

            st.session_state.selected_ranges[doc_id] = (
                1,
                min(page_count, 25)
            )

        except Exception as exc:
            st.error(
                f"Could not open {name}: {exc}"
            )


# =========================================================
# EXTRACT ONLY REQUESTED PAGES
# =========================================================

def extract_page_text(doc, page_number):
    """
    page_number is 1-indexed.
    Extract text only when the user requests that page.
    OCR is attempted only when normal text extraction
    returns very little text.
    """

    cache_key = page_number

    if cache_key in doc["text_cache"]:
        return doc["text_cache"][cache_key]

    try:
        with pymupdf.open(
            stream=doc["data"],
            filetype="pdf"
        ) as pdf:

            page = pdf[page_number - 1]
            text = clean_text(page.get_text("text"))

            if len(text) < 25:
                try:
                    pix = page.get_pixmap(
                        matrix=pymupdf.Matrix(1.3, 1.3),
                        alpha=False
                    )

                    image = Image.open(
                        io.BytesIO(pix.tobytes("png"))
                    )

                    ocr_text = clean_text(
                        pytesseract.image_to_string(image)
                    )

                    if len(ocr_text) > len(text):
                        text = ocr_text

                    doc["ocr_used"] = True

                except Exception as exc:
                    doc["ocr_errors"][page_number] = str(exc)

            doc["text_cache"][cache_key] = text

            return text

    except Exception as exc:
        return f"[Could not read page {page_number}: {exc}]"


def get_selected_range(doc_id, doc):
    default_start = 1
    default_end = min(doc["page_count"], 25)

    saved = st.session_state.selected_ranges.get(
        doc_id,
        (default_start, default_end)
    )

    start = max(1, min(saved[0], doc["page_count"]))
    end = max(start, min(saved[1], doc["page_count"]))

    return start, end


def get_selected_context(category="course"):
    documents = get_documents(category)
    chunks = []

    for doc_id, doc in documents.items():
        start, end = get_selected_range(doc_id, doc)

        for page_number in range(start, end + 1):
            text = extract_page_text(doc, page_number)

            if text and not text.startswith("[Could not read"):
                chunks.append(
                    f"Source: {doc['name']}, "
                    f"PDF page {page_number}\n{text}"
                )

    return "\n\n".join(chunks)


# =========================================================
# GEMINI
# =========================================================

def ask_gemini(prompt):
    client = get_gemini_client()

    if client is None:
        return (
            "Gemini API key is missing. Set the "
            "GEMINI_API_KEY environment variable and restart "
            "SmartMtutor."
        )

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt
        )

        if response.text:
            return response.text

        return "The AI returned an empty response. Please try again."

    except Exception as exc:
        return (
            "The AI request failed. Please check your internet "
            "connection, API key, model availability, and API quota.\n\n"
            f"Details: {exc}"
        )


def parse_json_response(response):
    try:
        return json.loads(response)

    except Exception:
        match = re.search(
            r"\{.*\}|\[.*\]",
            response,
            re.DOTALL
        )

        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass

    return None


# =========================================================
# PAGE IMAGE PREVIEW
# =========================================================

def render_pdf_page(doc, page_number):
    try:
        with pymupdf.open(
            stream=doc["data"],
            filetype="pdf"
        ) as pdf:

            page = pdf[page_number - 1]

            pix = page.get_pixmap(
                matrix=pymupdf.Matrix(1.1, 1.1),
                alpha=False
            )

            return Image.open(
                io.BytesIO(pix.tobytes("png"))
            )

    except Exception:
        return None


# =========================================================
# TOPIC DETECTION
# =========================================================

def detect_topics(text):
    patterns = [
        "Introduction",
        "Working Principle",
        "Block Diagram",
        "Applications",
        "Advantages",
        "Disadvantages",
        "Conclusion",
        "Communication",
        "Modulation",
        "Demodulation",
        "Sampling",
        "Quantization",
        "Digital Signal Processing",
        "Fourier Transform",
        "Filtering",
        "Sensors",
        "Instrumentation",
        "Microcontroller",
        "Embedded Systems",
        "Error Control Coding"
    ]

    found = []

    for topic in patterns:
        if topic.lower() in text.lower():
            found.append(topic)

    return found


def update_mastery(topic, percentage):
    previous = st.session_state.topic_mastery.get(topic)

    if previous is None:
        st.session_state.topic_mastery[topic] = percentage
    else:
        st.session_state.topic_mastery[topic] = (
            previous + percentage
        ) / 2

    st.session_state.topic_attempts[topic] = (
        st.session_state.topic_attempts.get(topic, 0) + 1
    )


# =========================================================
# HEADER AND NAVIGATION
# =========================================================

st.title("📚 SmartMtutor")
st.caption(
    "Personalized tutoring and adaptive learning "
    "based on your study materials."
)

with st.sidebar:
    st.header("Navigation")

    menu = st.radio(
        "Choose a section",
        [
            "Course Material",
            "AI Tutor",
            "Quiz",
            "Learning Dashboard",
            "Frequently Asked",
            "PYQ Analysis"
        ],
        key="main_navigation"
    )

    st.divider()

    st.caption("Study smart. Learn step by step.")


# =========================================================
# COURSE MATERIAL
# =========================================================

if menu == "Course Material":

    st.header("📚 Course Material")

    st.write(
        "Upload a PDF, choose a page range, and display "
        "only the pages you want to study."
    )

    uploaded_files = st.file_uploader(
        "Upload course PDFs",
        type=["pdf"],
        accept_multiple_files=True,
        key="course_material_uploader"
    )

    if uploaded_files:
        add_uploaded_documents(
            uploaded_files,
            category="course"
        )

    course_docs = get_documents("course")

    if not course_docs:
        st.info("Upload a PDF to begin.")
    else:
        st.success(
            f"{len(course_docs)} course PDF(s) available."
        )

        for doc_id, doc in list(course_docs.items()):

            st.divider()

            st.subheader(doc["name"])

            st.write(
                f"Total pages: **{doc['page_count']}**"
            )

            # PAGE RANGE CONTROLS ARE SHOWN IMMEDIATELY.
            old_start, old_end = get_selected_range(
                doc_id,
                doc
            )

            col1, col2 = st.columns(2)

            with col1:
                start_page = st.number_input(
                    "Start Page",
                    min_value=1,
                    max_value=doc["page_count"],
                    value=old_start,
                    step=1,
                    key=f"start_{doc_id}"
                )

            with col2:
                end_page = st.number_input(
                    "End Page",
                    min_value=int(start_page),
                    max_value=doc["page_count"],
                    value=max(int(start_page), old_end),
                    step=1,
                    key=f"end_{doc_id}"
                )

            st.session_state.selected_ranges[doc_id] = (
                int(start_page),
                int(end_page)
            )

            col_display, col_remove = st.columns(2)

            with col_display:
                display_clicked = st.button(
                    "Display Pages",
                    key=f"display_{doc_id}"
                )

            with col_remove:
                remove_clicked = st.button(
                    "Remove PDF",
                    key=f"remove_{doc_id}"
                )

            if remove_clicked:
                del st.session_state.course_docs[doc_id]

                st.session_state.selected_ranges.pop(
                    doc_id,
                    None
                )

                st.session_state.displayed_pages.pop(
                    doc_id,
                    None
                )

                st.rerun()

            if display_clicked:
                st.session_state.displayed_pages[doc_id] = (
                    int(start_page),
                    int(end_page)
                )

            displayed = st.session_state.displayed_pages.get(
                doc_id
            )

            if displayed:
                display_start, display_end = displayed

                st.subheader(
                    f"Pages {display_start}–{display_end}"
                )

                for page_number in range(
                    display_start,
                    display_end + 1
                ):
                    with st.expander(
                        f"PDF Page {page_number}",
                        expanded=(page_number == display_start)
                    ):
                        image = render_pdf_page(
                            doc,
                            page_number
                        )

                        if image is not None:
                            st.image(
                                image,
                                use_container_width=True
                            )

                        if st.button(
                            f"Extract Text from Page {page_number}",
                            key=f"extract_{doc_id}_{page_number}"
                        ):
                            with st.spinner(
                                f"Reading page {page_number}..."
                            ):
                                text = extract_page_text(
                                    doc,
                                    page_number
                                )

                                st.session_state.studied_pages.add(
                                    f"{doc_id}:{page_number}"
                                )

                                st.session_state[
                                    f"text_{doc_id}_{page_number}"
                                ] = text

                        extracted = st.session_state.get(
                            f"text_{doc_id}_{page_number}"
                        )

                        if extracted:
                            st.text_area(
                                "Extracted text",
                                value=extracted,
                                height=200,
                                key=f"viewtext_{doc_id}_{page_number}"
                            )

                st.caption(
                    "Text is extracted only when requested. "
                    "Scanned pages may take longer because OCR is used."
                )

            if doc["ocr_errors"]:
                with st.expander("OCR errors"):
                    st.write(doc["ocr_errors"])

        if st.button(
            "Remove All Course PDFs",
            key="remove_all_course"
        ):
            st.session_state.course_docs.clear()
            st.session_state.displayed_pages.clear()
            st.session_state.selected_ranges.clear()
            st.rerun()


# =========================================================
# AI TUTOR
# =========================================================

elif menu == "AI Tutor":

    st.header("🤖 AI Tutor")

    course_docs = get_documents("course")

    if not course_docs:
        st.warning(
            "Upload course material in Course Material first."
        )
    else:
        st.write(
            "The tutor uses the selected page ranges from "
            "your uploaded course PDFs."
        )

        question = st.text_area(
            "Ask a question",
            value=st.session_state.get(
                "faq_question_to_ask",
                ""
            ),
            placeholder=(
                "Example: Explain the working principle "
                "in an 8-mark VTU answer."
            ),
            key="ai_tutor_question"
        )

        if st.button("Get Answer", key="get_tutor_answer"):

            if not question.strip():
                st.warning("Enter a question first.")

            else:
                with st.spinner(
                    "Reading selected pages and preparing an answer..."
                ):
                    context = get_selected_context("course")

                    if not context.strip():
                        answer = (
                            "No readable text was found in the selected "
                            "pages. Check the PDF or try displaying and "
                            "extracting the pages in Course Material."
                        )

                    else:
                        prompt = f"""
You are SmartMtutor, a helpful VTU ECE tutor.

Use the provided course material as your primary source.

Rules:
1. Do not invent facts not supported by the material.
2. If the answer is not found in the material, say so clearly.
3. Use simple English suitable for a beginner.
4. For an 8-mark answer, organize the answer using:
   Definition, Principle, Working, Explanation,
   Important Points, Diagram Description,
   Applications, and Conclusion, where relevant.
5. Cite the PDF filename and page number when possible.

COURSE MATERIAL:
{context[:25000]}

STUDENT QUESTION:
{question}
"""

                        answer = ask_gemini(prompt)

                st.session_state.chat_history.append({
                    "question": question,
                    "answer": answer,
                    "date": datetime.now().strftime(
                        "%Y-%m-%d %H:%M"
                    )
                })

                st.session_state.faq_counter[question] = (
                    st.session_state.faq_counter.get(question, 0) + 1
                )

                st.session_state.faq_question_to_ask = ""

                st.subheader("Answer")
                st.markdown(answer)

        if st.session_state.chat_history:
            st.divider()
            st.subheader("Previous Questions")

            for item in reversed(
                st.session_state.chat_history[-10:]
            ):
                with st.expander(item["question"]):
                    st.markdown(item["answer"])


# =========================================================
# QUIZ
# =========================================================

elif menu == "Quiz":

    st.header("📝 Adaptive Quiz")

    course_docs = get_documents("course")

    if not course_docs:
        st.warning(
            "Upload course material before creating a quiz."
        )

    else:
        topic = st.text_input(
            "Quiz topic",
            placeholder="Example: Sampling theorem"
        )

        number_of_questions = st.selectbox(
            "Number of questions",
            [5, 10, 15],
            index=0
        )

        if st.button("Generate Quiz", key="generate_quiz"):

            with st.spinner(
                "Preparing questions from selected pages..."
            ):
                context = get_selected_context("course")

                if not context.strip():
                    st.error(
                        "No readable text was found in the selected pages."
                    )

                else:
                    prompt = f"""
Create {number_of_questions} multiple-choice questions
from the course material below.

Topic: {topic if topic.strip() else "All selected topics"}

Return only a valid JSON array.
Each object must contain:
- question: string
- options: array of exactly four strings
- answer: exact text of the correct option
- explanation: string
- topic: string

Use only information supported by the material.

COURSE MATERIAL:
{context[:20000]}
"""

                    response = ask_gemini(prompt)
                    parsed = parse_json_response(response)

                    if isinstance(parsed, list) and parsed:
                        valid_questions = []

                        for item in parsed:
                            if (
                                isinstance(item, dict)
                                and item.get("question")
                                and isinstance(item.get("options"), list)
                                and len(item["options"]) == 4
                                and item.get("answer") in item["options"]
                            ):
                                valid_questions.append(item)

                        if valid_questions:
                            st.session_state.quiz_questions = (
                                valid_questions
                            )

                            st.session_state.quiz_answers = {}
                            st.session_state.quiz_submitted = False
                            st.session_state.quiz_results = []

                            st.rerun()

                        else:
                            st.error(
                                "The generated questions were not in "
                                "the expected format. Please try again."
                            )

                    else:
                        st.error(
                            "Could not generate a valid quiz. "
                            "Please try again."
                        )

        questions = st.session_state.quiz_questions

        if questions:

            st.divider()
            st.subheader("Your Quiz")

            if not st.session_state.quiz_submitted:

                with st.form("quiz_form"):

                    for i, q in enumerate(questions):

                        st.markdown(
                            f"**Q{i + 1}. {q['question']}**"
                        )

                        answer = st.radio(
                            "Choose an answer",
                            q["options"],
                            index=None,
                            key=f"quiz_answer_{i}"
                        )

                        st.session_state.quiz_answers[i] = answer

                    submitted = st.form_submit_button(
                        "Submit Quiz"
                    )

                if submitted:

                    results = []
                    correct_count = 0

                    for i, q in enumerate(questions):
                        selected = st.session_state.quiz_answers.get(i)
                        correct = q["answer"]

                        is_correct = (
                            selected is not None
                            and selected.strip().casefold()
                            == correct.strip().casefold()
                        )

                        if is_correct:
                            correct_count += 1

                        results.append({
                            "question": q["question"],
                            "selected": selected,
                            "correct": correct,
                            "is_correct": is_correct,
                            "explanation": q.get("explanation", ""),
                            "topic": q.get("topic", topic or "General")
                        })

                    percentage = (
                        correct_count / len(questions)
                    ) * 100

                    st.session_state.quiz_results = results
                    st.session_state.quiz_submitted = True

                    for item in results:
                        update_mastery(
                            item["topic"],
                            100 if item["is_correct"] else 0
                        )

                    st.session_state.quiz_history.append({
                        "date": datetime.now().strftime(
                            "%Y-%m-%d %H:%M"
                        ),
                        "topic": topic or "General",
                        "score": correct_count,
                        "total": len(questions),
                        "percentage": round(percentage, 1)
                    })

                    st.rerun()

            else:

                results = st.session_state.quiz_results

                correct_count = sum(
                    item["is_correct"] for item in results
                )

                total = len(results)

                st.metric(
                    "Your Score",
                    f"{correct_count}/{total}"
                )

                st.progress(
                    correct_count / total if total else 0
                )

                for i, item in enumerate(results):

                    with st.expander(
                        f"Question {i + 1}: "
                        f"{'Correct' if item['is_correct'] else 'Review'}"
                    ):
                        st.write(item["question"])
                        st.write(
                            f"Your answer: {item['selected'] or 'Not answered'}"
                        )
                        st.write(
                            f"Correct answer: {item['correct']}"
                        )
                        st.write(item["explanation"])

                if st.button(
                    "Create Another Quiz",
                    key="another_quiz"
                ):
                    st.session_state.quiz_questions = []
                    st.session_state.quiz_answers = {}
                    st.session_state.quiz_submitted = False
                    st.session_state.quiz_results = []
                    st.rerun()


# =========================================================
# LEARNING DASHBOARD
# =========================================================

elif menu == "Learning Dashboard":

    st.header("📊 Learning Dashboard")

    course_docs = get_documents("course")

    total_pages = sum(
        doc["page_count"] for doc in course_docs.values()
    )

    studied_pages = len(
        st.session_state.studied_pages
    )

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Course PDFs",
        len(course_docs)
    )

    col2.metric(
        "Total PDF Pages",
        total_pages
    )

    col3.metric(
        "Pages Studied",
        studied_pages
    )

    progress = (
        min(studied_pages / total_pages, 1.0)
        if total_pages else 0
    )

    st.subheader("Study Progress")
    st.progress(progress)

    st.write(f"{progress * 100:.1f}% of pages marked as studied.")

    st.divider()
    st.subheader("Topic Mastery")

    mastery = st.session_state.topic_mastery

    if mastery:

        for topic, score in mastery.items():
            st.write(f"**{topic}** — {score:.1f}%")
            st.progress(max(0.0, min(score / 100, 1.0)))

        weak_topics = [
            topic for topic, score in mastery.items()
            if score < 60
        ]

        if weak_topics:
            st.warning(
                "Topics to revise: " + ", ".join(weak_topics)
            )

    else:
        st.info(
            "Complete a quiz to start recording topic mastery."
        )

    st.divider()
    st.subheader("Quiz History")

    if st.session_state.quiz_history:
        st.dataframe(
            st.session_state.quiz_history,
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Your quiz results will appear here.")


# =========================================================
# FREQUENTLY ASKED
# =========================================================

elif menu == "Frequently Asked":

    st.header("❓ Frequently Asked Questions")

    faqs = st.session_state.faq_counter

    if faqs:

        for question, count in sorted(
            faqs.items(),
            key=lambda item: item[1],
            reverse=True
        ):

            with st.expander(
                f"{question} — Asked {count} time(s)"
            ):

                st.write(
                    "This question has been asked "
                    f"{count} time(s)."
                )

                if st.button(
                    "Ask again in AI Tutor",
                    key="faq_" + hashlib.md5(
                        question.encode()
                    ).hexdigest()
                ):
                    st.session_state.faq_question_to_ask = question
                    st.session_state.main_navigation = "AI Tutor"
                    st.rerun()

        if st.button("Clear FAQ History"):
            st.session_state.faq_counter.clear()
            st.rerun()

    else:
        st.info(
            "Ask questions in AI Tutor. They will appear here."
        )


# =========================================================
# PYQ ANALYSIS
# =========================================================

elif menu == "PYQ Analysis":

    st.header("🔎 Previous Year Question Analysis")

    st.write(
        "Upload previous-year question papers. The app will "
        "compare extracted page text to find potentially "
        "similar pages."
    )

    uploaded_pyqs = st.file_uploader(
        "Upload PYQ PDFs",
        type=["pdf"],
        accept_multiple_files=True,
        key="pyq_uploader"
    )

    if uploaded_pyqs:
        add_uploaded_documents(
            uploaded_pyqs,
            category="pyq"
        )

    pyq_docs = get_documents("pyq")

    if not pyq_docs:
        st.info("Upload PYQ papers to begin.")

    else:

        for doc_id, doc in list(pyq_docs.items()):

            col1, col2 = st.columns([4, 1])

            with col1:
                st.write(f"**{doc['name']}**")
                st.write(
                    f"Pages: {doc['page_count']}"
                )

            with col2:
                if st.button(
                    "Remove",
                    key=f"remove_pyq_{doc_id}"
                ):
                    del st.session_state.pyq_docs[doc_id]
                    st.session_state.pyq_results = []
                    st.rerun()

        st.divider()

        if st.button(
            "Find Repeated Questions",
            key="find_repeated_questions"
        ):

            page_entries = []

            with st.spinner(
                "Extracting text from PYQ pages. "
                "Scanned pages may take longer..."
            ):

                for doc in pyq_docs.values():

                    for page_number in range(
                        1,
                        doc["page_count"] + 1
                    ):

                        text = extract_page_text(
                            doc,
                            page_number
                        )

                        if text and not text.startswith(
                            "[Could not read"
                        ):
                            page_entries.append({
                                "paper": doc["name"],
                                "page": page_number,
                                "text": text
                            })

                results = []

                for i in range(len(page_entries)):

                    first = page_entries[i]

                    for j in range(i + 1, len(page_entries)):

                        second = page_entries[j]

                        if (
                            first["paper"] == second["paper"]
                            and first["page"] == second["page"]
                        ):
                            continue

                        similarity = SequenceMatcher(
                            None,
                            first["text"].lower(),
                            second["text"].lower()
                        ).ratio()

                        if similarity >= 0.35:
                            results.append({
                                "Paper 1": first["paper"],
                                "Page 1": first["page"],
                                "Paper 2": second["paper"],
                                "Page 2": second["page"],
                                "Similarity (%)": round(
                                    similarity * 100,
                                    1
                                )
                            })

                results.sort(
                    key=lambda row: row["Similarity (%)"],
                    reverse=True
                )

                st.session_state.pyq_results = results

        results = st.session_state.pyq_results

        if results:

            st.subheader("Potentially Similar Pages")

            st.caption(
                "Text similarity is only an indicator. "
                "It does not confirm that the exact same "
                "question has been repeated."
            )

            st.dataframe(
                results[:100],
                use_container_width=True,
                hide_index=True
            )

        elif st.session_state.pyq_results == []:

            st.info(
                "Click Find Repeated Questions to start the analysis."
            )


# =========================================================
# FOOTER
# =========================================================

st.divider()

st.caption(
    "SmartMtutor | Personalized tutoring and adaptive learning"
)
