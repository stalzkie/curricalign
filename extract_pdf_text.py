import fitz
# PyMuPDF;
# others such as PDFplumber and
# PyPDF2 probs work too, just don't use
# VS Code like I did

def extract_text_from_pdf(pdf_path):
    text = ""
    with fitz.open(pdf_path) as doc:
        for page in doc:
            text += page.get_text()
    return text

if __name__ == "__main__":
    pdf_file = "Computer-Science-Game-Design.pdf"  # Change this to the PDF file name
    extracted_text = extract_text_from_pdf(pdf_file)
    print(extracted_text)
