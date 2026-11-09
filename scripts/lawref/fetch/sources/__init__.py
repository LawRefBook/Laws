"""数据源：国家法律法规数据库（flk）、国家规章库（gov）、维基文库（wikisource）。"""
from .base import Provider
from .flk import FlkQuery, NationalLawDatabaseProvider
from .gov import GovRegulationDatabaseProvider
from .wikisource import WikisourceProvider

__all__ = ["FlkQuery", "GovRegulationDatabaseProvider", "NationalLawDatabaseProvider", "Provider", "WikisourceProvider"]
