# SmartMtutor
### AI-Powered Personalized Tutoring and Adaptive Learning

## 1. Overview

SmartMtutor is an AI-powered learning platform designed to help students
understand academic subjects using their own course materials.

The platform allows students to upload course PDFs and previous-year
question papers, ask questions about selected pages, generate quizzes,
monitor learning progress, and explore frequently asked questions.

SmartMtutor aims to make learning more accessible, organized, and
personalized.

## 2. Problem Statement

Students often spend considerable time searching through textbooks,
lecture notes, and previous-year question papers to understand difficult
concepts and prepare for examinations.

Traditional study methods may not provide immediate explanations,
personalized practice, or a convenient way to identify topics that need
more attention.

## 3. Proposed Solution

SmartMtutor combines document processing, generative AI, and interactive
learning features in one web application.

Students can study from uploaded course materials, ask questions about
specific page ranges, practice through quizzes, and review their
learning progress.

## 4. Key Features

### Course Material
- Upload PDF course materials.
- Select specific page ranges for studying.
- Extract text from supported documents.
- Review relevant study material.

### AI Tutor
- Ask questions about uploaded course materials.
- Receive AI-generated explanations.
- Focus tutoring questions on selected study pages.

### Quiz
- Generate quizzes based on study material.
- Practice concepts interactively.
- Review quiz performance.

### Learning Dashboard
- View available learning-progress information.
- Review recorded quiz results and topic mastery where supported.

### Frequently Asked Questions
- Submit questions about study material.
- Review frequently asked questions.

### Previous-Year Question Analysis
- Analyze uploaded previous-year question papers.
- Explore potentially repeated questions and related material.

Note: The reliability and completeness of PYQ analysis depend on the
document content and the current implementation.

## 5. Technology Stack

- Python — application logic
- Streamlit — interactive web application
- Google Gemini API — generative AI
- PyMuPDF — PDF text extraction
- Pytesseract — OCR integration
- Pillow — image processing

## 6. System Workflow

1. The student uploads course material or question papers.
2. SmartMtutor processes the available document content.
3. The student selects study pages and asks questions.
4. The AI Tutor generates explanations using the available context.
5. The student practices with quizzes.
6. The dashboard displays recorded learning information.

## 7. Live Application

https://smartmtutor09mm15.streamlit.app/

## 8. Run Locally

### Requirements
- Python 3.10 or a compatible Python version
- The dependencies listed in requirements.txt
- A Google Gemini API key

### Installation

Clone the repository:

    git clone https://github.com/mehnaz15/smartmtutor.git

Enter the project folder:

    cd smartmtutor

Create a virtual environment:

    python -m venv venv

Activate it on Windows:

    venv\Scripts\activate

Install dependencies:

    python -m pip install -r requirements.txt

Configure the GEMINI_API_KEY environment variable, then run:

    python -m streamlit run app.py

Open the local URL displayed in the terminal.

## 9. Responsible Use and Limitations

- AI-generated explanations can contain errors and should be checked
  against course materials.
- Results depend on the quality and readability of uploaded documents.
- OCR may require additional system configuration.
- PYQ analysis may not identify every repeated question.
- Learning progress and uploaded documents may not persist across
  sessions unless persistent storage is configured.
- API usage may be subject to provider limits and charges.

## 10. Future Scope

- Improve repeated-question detection.
- Add reliable source citations with page references.
- Integrate lecture-video learning and timestamp references.
- Improve personalized learning recommendations.
- Add persistent learner profiles and progress storage.
- Evaluate answer accuracy and learning outcomes.

## 11. Project Goal

SmartMtutor aims to provide a unified learning environment that combines
academic documents, AI tutoring, quizzes, and progress tracking to
support students in their examination preparation and independent study.
