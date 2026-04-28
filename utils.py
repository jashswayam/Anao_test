import os
import zipfile
import subprocess
import base64
import httpx
from typing import List, Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from PyPDF2 import PdfReader

class AIOrchestrator:
    def __init__(self, l1_config, l2_config, timeout: int = 60):
        self.l1_config = l1_config
        self.l2_config = l2_config
        
        # Initialize a custom HTTP client
        self.http_client = httpx.Client(
            timeout=httpx.Timeout(timeout),
            follow_redirects=True
        )
        
        # Layer 1: Vision Model
        self.l1_llm = ChatOpenAI(
            api_key=l1_config['api_key'],
            base_url=l1_config['base_url'],
            model=l1_config['model_name'],
            http_client=self.http_client
        )
        
        # Layer 2: Reasoning Model
        self.l2_llm = ChatOpenAI(
            api_key=l2_config['api_key'],
            base_url=l2_config['base_url'],
            model=l2_config['model_name'],
            http_client=self.http_client
        )

    def process_document(self, file_bytes, file_name, file_type):
        """Converts FSD/TSD (PDF/Image) to Markdown using L1 Vision Model."""
        
        if file_type == "application/pdf":
            # Simple text extraction as fallback, but for Vision we should ideally send images of pages
            # For this prototype, if it's a PDF, we'll try to extract text first, 
            # or the user can use a vision model that accepts PDF bytes if supported by the provider.
            # Most OpenAI compatible vision models expect images.
            # We'll just provide a prompt asking to summarize/convert to MD.
            
            # TODO: Add pdf2image conversion for better vision support
            reader = PdfReader(file_bytes)
            content = ""
            for page in reader.pages:
                content += page.extract_text() + "\n"
                
            prompt = f"Convert the following document content into a clean, structured Markdown file. Document Name: {file_name}\n\nContent:\n{content}"
            response = self.l1_llm.invoke(prompt)
            return response.content
        else:
            # Handle Images
            base64_image = base64.b64encode(file_bytes.getvalue()).decode('utf-8')
            message = HumanMessage(
                content=[
                    {"type": "text", "text": "Extract all information from this document image and format it as a structured Markdown file."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{file_type};base64,{base64_image}"},
                    },
                ]
            )
            response = self.l1_llm.invoke([message])
            return response.content

    def generate_test_plan(self, fsd_md, tsd_md, codebase_summary):
        """Generates testing.md using L2 Reasoning Model."""
        prompt = f"""
        Analyze the following Functional Specification (FSD), Technical Specification (TSD), and Project Codebase summary.
        
        FSD:
        {fsd_md}
        
        TSD:
        {tsd_md}
        
        Codebase Summary:
        {codebase_summary}
        
        Based on these, create a 'testing.md' file. 
        It must include:
        1. Identification of Frontend and Backend components.
        2. Unit Testing references (what should be tested in each unit).
        3. Integration/Flow Testing scenarios.
        4. Recommended testing frameworks (e.g., Pytest for backend, Robot Framework for frontend).
        
        Output ONLY the Markdown content for 'testing.md'.
        """
        response = self.l2_llm.invoke(prompt)
        return response.content

    def generate_test_files(self, testing_md, codebase_summary):
        """Generates executable test files based on testing.md."""
        prompt = f"""
        Based on the following Test Plan (testing.md) and Codebase Summary, generate executable test files.
        
        Testing Plan:
        {testing_md}
        
        Codebase Summary:
        {codebase_summary}
        
        Generate the actual code for:
        1. Backend Unit Tests (e.g., using Pytest if Python, JUnit if Java).
        2. Frontend Tests (e.g., using Robot Framework or Playwright).
        
        Format your response as a list of files with their content like this:
        FILE: path/to/test_file.py
        CONTENT:
        <code>
        ---
        FILE: path/to/another_test.robot
        CONTENT:
        <code>
        
        Ensure the paths are relative to the project root.
        """
        response = self.l2_llm.invoke(prompt)
        return response.content

def extract_zip(zip_bytes, extract_to):
    with zipfile.ZipFile(zip_bytes, 'r') as zip_ref:
        zip_ref.extractall(extract_to)

def get_codebase_summary(root_dir):
    summary = ""
    for root, dirs, files in os.walk(root_dir):
        # Skip hidden folders and common non-code folders
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', '__pycache__', 'venv']]
        for file in files:
            if file.endswith(('.py', '.java', '.js', '.ts', '.html', '.css', '.robot')):
                rel_path = os.path.relpath(os.path.join(root, file), root_dir)
                summary += f"- {rel_path}\n"
    return summary

def parse_and_save_test_files(raw_content, root_dir):
    """Parses the LLM output and saves files to the root_dir."""
    files = raw_content.split('---')
    saved_files = []
    for file_block in files:
        if "FILE:" in file_block and "CONTENT:" in file_block:
            try:
                parts = file_block.split("CONTENT:")
                file_path_line = parts[0].strip()
                content = parts[1].strip()
                
                # Extract actual path
                file_path = file_path_line.replace("FILE:", "").strip()
                full_path = os.path.join(root_dir, file_path)
                
                # Create directories if needed
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                
                with open(full_path, 'w') as f:
                    f.write(content)
                saved_files.append(file_path)
            except Exception as e:
                print(f"Error parsing file block: {e}")
    return saved_files

def run_test_command(command: str, cwd: str):
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, check=False, cwd=cwd)
        return f"Command: {command}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}\n"
    except Exception as e:
        return f"Error running command {command}: {str(e)}\n"
