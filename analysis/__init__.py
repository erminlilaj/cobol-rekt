"""
COBOL Analysis Package

This package provides tools for analyzing COBOL source code:
- SandboxEnvironment: Isolated analysis with auto-stubbing
- preprocess_file/preprocess_directory: Syntax normalization
- evaluate: Diagnostic reporting
- detect_dialect: Auto-detect IDMS vs standard COBOL
"""

from .sandbox_manager import SandboxEnvironment, create_sandbox, Colors
from .cobol_preprocessor import preprocess_file, preprocess_directory
from .evaluate import run_evaluation, parse_error_output, analyze_copybook_health

__all__ = [
    'SandboxEnvironment',
    'create_sandbox', 
    'Colors',
    'preprocess_file',
    'preprocess_directory',
    'run_evaluation',
    'parse_error_output',
    'analyze_copybook_health',
]
