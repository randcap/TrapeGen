"""Parametric trapezoid assembly regions for STL solids."""

from .config import GeometryError, Tolerances
from .pipeline import GenerationResult, TrapezoidGenerator, generate_trapezoid_region

__all__ = [
    "GenerationResult", "GeometryError", "Tolerances", "TrapezoidGenerator",
    "generate_trapezoid_region",
]
