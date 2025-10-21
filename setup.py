#!/usr/bin/env python3
"""
Setup script for La Centrale Scraper
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="lacentrale-scraper",
    version="1.0.0",
    author="Your Name",
    author_email="your.email@example.com",
    description="A powerful web scraper for La Centrale car listings",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/lacentrale-scraper",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Internet :: WWW/HTTP :: Browsers",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "lacentrale-scraper=scraper_cdp:main",
        ],
    },
    keywords="web-scraping, cars, la-centrale, playwright, python",
    project_urls={
        "Bug Reports": "https://github.com/yourusername/lacentrale-scraper/issues",
        "Source": "https://github.com/yourusername/lacentrale-scraper",
    },
)
