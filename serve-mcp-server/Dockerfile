FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port for SSE transport
EXPOSE 8004

# Run MCP server with SSE transport for HTTP access
CMD ["python", "main.py", "--http"]
