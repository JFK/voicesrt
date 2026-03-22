import os

import pytest

# Set test encryption key before importing app modules
os.environ["ENCRYPTION_KEY"] = "dGVzdC1lbmNyeXB0aW9uLWtleS0xMjM0NTY3ODkwMTI="


@pytest.fixture
def sample_segments():
    return [
        {"start": 0.0, "end": 2.5, "text": "Hello, welcome to the video."},
        {"start": 3.0, "end": 5.8, "text": "Today we will discuss Python."},
        {"start": 6.0, "end": 10.2, "text": "Let's get started."},
    ]
