import os
import pandas as pd
from pypdf import PdfReader
from docx import Document
try:
    import win32com.client
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False

def convert_doc_to_docx(doc_path: str) -> str:
    """Uses Microsoft Word to convert old .doc file into .docx (Windows only)."""
    if not WIN32_AVAILABLE:
        raise RuntimeError(
            "Legacy .doc conversion requires 'pywin32' and Microsoft Word, which are only available on Windows. "
            "Please upload your file as .docx, .pdf, or .txt for Linux VPS deployment."
        )
    
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False

    doc = word.Documents.Open(os.path.abspath(doc_path))
    new_path = doc_path + "x"

    doc.SaveAs(os.path.abspath(new_path), FileFormat=16)
    doc.Close()
    word.Quit()

    return new_path

def extract_text_from_docx(docx_path: str) -> str:
    """Extracts text from a valid .docx file."""
    document = Document(docx_path)
    return "\n".join([para.text for para in document.paragraphs])

def extract_text_from_excel(file_path: str) -> str:
    """Extracts text from an Excel or CSV file."""
    try:
        if file_path.endswith(".csv"):
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path)
        
        # Convert the dataframe to a clean text representation
        text = df.to_string(index=False)
        return text
    except Exception as e:
        return f"Error extracting from spreadsheet: {str(e)}"

def extract_text(file_path: str) -> str:
    """
    Main extractor supporting PDF, DOCX, DOC, TXT, XLSX, CSV.
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text

    if ext == ".docx":
        return extract_text_from_docx(file_path)

    if ext == ".doc":
        converted_path = convert_doc_to_docx(file_path)
        return extract_text_from_docx(converted_path)

    if ext == ".txt":
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
            
    if ext in [".xlsx", ".xls", ".csv"]:
        return extract_text_from_excel(file_path)

    raise ValueError("Unsupported file type. Only PDF, DOC, DOCX, TXT, XLSX, CSV are allowed.")

def generate_uk_restaurant_prompt(business_rules: str, menu_text: str) -> str:
    """
    Generates a highly optimized System Prompt for a UK Restaurant/Takeaway.
    """
    # Get the absolute path to the prompt file (in case this script is run from a different directory)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    prompt_path = os.path.join(base_dir, "uk_system_prompt.txt")
    
    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt_template = f.read()
        
    prompt = prompt_template.format(business_rules=business_rules, menu_text=menu_text)
    return prompt
