
# Stage 1: Backend Builder
FROM python:3.11-slim AS backend-builder

# Setup working directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Copy backend code
COPY . .

# Stage 2: Backend Runtime
FROM python:3.11-slim

# Setup working directory
WORKDIR /app

# Copy installed dependencies from builder
COPY --from=backend-builder /install /usr/local

# Copy application code
COPY --from=backend-builder /app .

# Port
EXPOSE 8000

# Start FastAPI application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

