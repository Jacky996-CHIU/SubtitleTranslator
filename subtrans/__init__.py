"""SubtitleTranslator core package."""
from .extractor import Segment, SubtitleExtractor, ExtractConfig
from .ocr_engine import OCRConfig, build_engine
from .pipeline import JobConfig, JobResult, run_job

__all__ = [
    "Segment", "SubtitleExtractor", "ExtractConfig",
    "OCRConfig", "build_engine",
    "JobConfig", "JobResult", "run_job",
]
__version__ = "1.0.0"
