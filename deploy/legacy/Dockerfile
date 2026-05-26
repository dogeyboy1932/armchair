FROM python:3.12-slim

# Install system dependencies required for psycopg2 and other C-extentions
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download NLTK data required by keybert/nltk
RUN python -m nltk.downloader punkt punkt_tab stopwords

# Copy the rest of the application
COPY . .

# Expose the API port
EXPOSE 8080

# Run Uvicorn backend
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
