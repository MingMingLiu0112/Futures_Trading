from setuptools import setup, find_packages
import os

# 读取版本号
def get_version():
    """读取版本号"""
    with open(os.path.join(os.path.dirname(__file__), "VERSION"), "r", encoding="utf-8") as f:
        return f.read().strip()

setup(
    name="vnpy_tianqin",
    version=get_version(),
    description="TqSdk Gateway for VeighNa",
    long_description="""
    TqSdk Gateway for VeighNa Trading Platform
    
    Features:
    - Support for TqSdk API
    - Support for futures and options trading
    - Support for account and position data
    - Support for order and trade data
    - Auto-generate contracts from TqSdk API
    - Support for option contracts
    - Support for datafeed
    """,
    long_description_content_type="text/markdown",
    
    author="VeighNa Team",
    author_email="vnpy@veighna.com",
    url="https://github.com/veighna/vnpy",
    
    license="MIT",
    
    packages=find_packages(),
    
    package_data={
        "vnpy/gateway/tqsdk": [
            "tqsdk_gateway.py",
            "option_parser.py",
            "datafeed.py",
            "__init__.py",
        ],
    },
    
    install_requires=[
        "vnpy>=3.0.0",
        "tqsdk>=2.0.0",
    ],
    
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Financial and Insurance Industry",
        "Topic :: Office/Business :: Financial :: Investment",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
    ],
    
    python_requires=">=3.7",
)
