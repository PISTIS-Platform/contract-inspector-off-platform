# Contract Inspector - Fingerprint Similarity Service

A FastAPI-based microservice for processing and storing contract fingerprints with similarity computation support. Part of the PISTIS contract inspection platform.

## Overview

This service provides an asynchronous API for accepting fingerprint URLs, validating their availability, downloading fingerprint data, and storing both the fingerprints and associated similarity result metadata in MinIO object storage.

## Features

- **Asynchronous Processing**: Immediate HTTP 202 acknowledgement with background processing
- **URL Validation**: Probes remote fingerprint URLs before accepting requests
- **Object Storage**: MinIO S3-compatible storage for fingerprints and results
- **Health Monitoring**: Built-in health check endpoint
- **Containerized Deployment**: Docker and Docker Compose support
- **Comprehensive Testing**: Integration tests with real MinIO instances

## Technology Stack

- **Python 3.12**
- **FastAPI 0.118.0** - Modern web framework
- **Uvicorn 0.37.0** - ASGI server
- **Pydantic 2.11.9** - Data validation and settings
- **MinIO 7.2.18** - S3-compatible object storage
- **Pytest 8.4.2** - Testing framework

## Project Structure

```
contract-inspector-off-platform/
├── app/
│   ├── main.py                   # FastAPI application entry point
│   ├── config.py                 # Configuration management
│   ├── schemas.py                # Request/response models
│   ├── routes/
│   │   ├── health.py            # Health check endpoint
│   │   └── similarity.py         # Similarity request endpoint
│   └── services/
│       ├── similarity.py         # Core similarity processing logic
│       └── minio_service.py      # MinIO client utilities
├── tests/
│   ├── conftest.py              # Pytest fixtures
│   ├── test_similarity_api.py    # Integration tests
│   └── data/                    # Test data files
├── Dockerfile                    # Container image definition
├── docker-compose.yaml           # Service orchestration
├── requirements.txt              # Python dependencies
└── pytest.ini                    # Pytest configuration
```

## API Endpoints

### Health Check

```http
GET /health
```

Returns service health status.

**Response** (200 OK):
```json
{
  "status": "ok"
}
```

### Similarity Request

```http
POST /similarity
```

Accepts a fingerprint URL for asynchronous processing.

**Request Body**:
```json
{
  "fingerprint_url": "http://example.com/fingerprint.csv",
  "dataset_id": "my-dataset"
}
```

**Response** (202 Accepted):
```json
{
  "dataset_id": "my-dataset",
  "fingerprint_url": "http://example.com/fingerprint.csv",
  "status": "acknowledged",
  "remote_object_available": true
}
```

**Error Responses**:
- `400 Bad Request` - Invalid dataset_id (blank or whitespace-only)
- `404 Not Found` - Fingerprint URL is not accessible
- `502 Bad Gateway` - Network error accessing fingerprint URL

## Configuration

Configuration is managed via environment variables:

### API Settings
- `LOG_LEVEL` - Logging verbosity (default: `INFO`)
- `SIMILARITY_API_NAME` - Service name (default: `Fingerprint Similarity Service`)
- `SIMILARITY_API_VERSION` - API version (default: `1.0.0`)

### MinIO Settings
- `LOCAL_MINIO_ENDPOINT` - MinIO endpoint (default: `localhost:9000`)
- `LOCAL_MINIO_ACCESS_KEY` - Access key (default: `minioadmin`)
- `LOCAL_MINIO_SECRET_KEY` - Secret key (default: `minioadmin`)
- `LOCAL_MINIO_BUCKET` - Bucket name (default: `pistis`)
- `LOCAL_MINIO_SECURE` - Use HTTPS (default: `false`)

### Storage Paths
- `FINGERPRINT_PREFIX` - Fingerprint storage prefix (default: `fingerprints`)
- `SIMILARITY_RESULT_PREFIX` - Result metadata prefix (default: `similarity`)

### Network Settings
- `REMOTE_URL_TIMEOUT_SECONDS` - Remote URL probe timeout (default: `5`)

## Getting Started

### Prerequisites

- Docker and Docker Compose
- Python 3.12+ (for local development)

### Running with Docker Compose

1. Start the service and MinIO storage:

```bash
docker-compose up -d
```

2. The API will be available at `http://localhost:8000`

3. MinIO console is accessible at `http://localhost:9090` (credentials: `localadmin` / `localsecret123`)

### Running Locally

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Start MinIO (using the provided compose file):

```bash
docker-compose -f minio-compose.yaml up -d
```

3. Run the application:

```bash
python similarity_api.py
```

The service will start on `http://localhost:8000`.

## Data Flow

1. Client sends POST request to `/similarity` with fingerprint URL and dataset ID
2. Service validates that dataset_id is non-blank
3. Service probes the remote URL with a HEAD request to confirm accessibility
4. If URL is inaccessible, returns HTTP 404 immediately
5. If URL is accessible, returns HTTP 202 and spawns background thread
6. Background thread:
   - Downloads fingerprint from the URL
   - Stores fingerprint to MinIO at `fingerprints/{dataset_id}/{filename}`
   - Generates similarity result metadata with empty matches array
   - Stores metadata to MinIO at `similarity/{dataset_id}/{filename}.json`

## Storage Structure

Fingerprints and results are stored in MinIO with the following structure:

```
pistis/
├── fingerprints/
│   └── {dataset_id}/
│       └── {filename}
└── similarity/
    └── {dataset_id}/
        └── {filename}.json
```

## Testing

Run the test suite:

```bash
pytest
```

The test suite includes integration tests that:
- Test successful fingerprint processing and storage
- Verify error handling for missing remote objects
- Use real MinIO instances (local and remote) for validation

## Development

### Adding New Endpoints

1. Create a new router in `app/routes/`
2. Define request/response schemas in `app/schemas.py`
3. Implement business logic in `app/services/`
4. Register the router in `app/main.py`

### Logging

The service uses Python's built-in logging. Log level can be controlled via the `LOG_LEVEL` environment variable:

```bash
export LOG_LEVEL=DEBUG
python similarity_api.py
```

## Docker Images

The service uses a multi-layer Docker image based on `python:3.12-slim`:

```bash
# Build the image
docker build -t contract-inspector-similarity .

# Run the container
docker run -p 8000:8000 contract-inspector-similarity
```

## License

[Specify your license here]

## Contributing

[Specify contribution guidelines here]

## Support

For issues and questions, please refer to the project's issue tracker.
