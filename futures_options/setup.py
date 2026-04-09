from setuptools import setup, find_packages

setup(
    name="futures-options",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "akshare>=1.13.0",
        "pandas>=2.0.0",
        "numpy>=1.24.0",
        "requests>=2.31.0",
        "python-dotenv>=1.0.0",
    ],
    python_requires=">=3.9",
)
