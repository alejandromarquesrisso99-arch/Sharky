from setuptools import setup, find_packages

setup(
    name="sharky-brain",
    version="1.0.0",
    description="Cerebro digital autónomo de inversión vinculado a Obsidian con instinto de supervivencia",
    author="Alejandro Marqués",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "anthropic>=0.40.0",
        "yfinance>=0.2.40",
        "pydantic>=2.7.0",
        "python-dotenv>=1.0.1",
        "pyyaml>=6.0.1",
        "rich>=13.7.0",
        "schedule>=1.2.0",
    ],
    entry_points={
        "console_scripts": [
            "sharky=sharky.cli:main",
        ],
    },
)
