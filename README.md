# Contract Inspector - Fingerprint Similarity Service

A FastAPI-based microservice for processing and storing contract fingerprints with similarity computation. Part of the PISTIS off platform contract inspection component.

## Overview

This service provides an asynchronous API for accepting fingerprint URLs, validating their availability, downloading fingerprint data, and storing both the fingerprints and associated similarity result metadata in MinIO object storage.

## Features

- **Asynchronous Processing**: Immediate HTTP 202 acknowledgement with background processing
- **URL Validation**: Probes remote fingerprint URLs before accepting requests
- **Similarity Computation**: Automatic MinHash-based Jaccard similarity calculation
- **Search API**: Query similarity results by dataset ID
- **Object Storage**: MinIO S3-compatible storage for fingerprints and results
- **Health Monitoring**: Built-in health check endpoint
- **Configurable Thresholds**: Adjustable similarity threshold for match filtering



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
│   ├── main.py                     # FastAPI application entry point
│   ├── config.py                   # Configuration management
│   ├── schemas.py                  # Request/response models
│   ├── routes/
│   │   ├── health.py              # Health check endpoint
│   │   ├── similarity.py           # Similarity request endpoint
│   │   └── search.py              # Search similarity results endpoint
│   └── services/
│       ├── similarity.py           # Core similarity processing logic
│       ├── similarity_search.py    # Similarity result retrieval
│       ├── minhash_similarity.py   # MinHash comparison algorithms
│       └── minio_service.py        # MinIO client utilities
├── tests/
│   ├── conftest.py                # Pytest fixtures
│   ├── test_similarity_api.py      # Integration tests
│   ├── test_minhash_similarity.py  # MinHash algorithm tests
│   ├── test_search_api.py          # Search endpoint tests
│   └── data/                      # Test data files
├── Dockerfile                      # Container image definition
├── docker-compose.yaml             # Service orchestration
├── openapi.yaml                    # OpenAPI 3.0 specification
├── requirements.txt                # Python dependencies
└── pytest.ini                      # Pytest configuration
```

## API Endpoints

The service provides both machine-readable and interactive API documentation:

- **OpenAPI Specification**: Available at [`openapi.yaml`](./openapi.yaml)
- **Interactive Docs (Swagger UI)**: `http://localhost:8000/docs`
- **Alternative Docs (ReDoc)**: `http://localhost:8000/redoc`
- **OpenAPI JSON**: `http://localhost:8000/openapi.json`

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

### Search Similarity Results

```http
GET /search?dataset_id={dataset_id}
```

Retrieves similarity results for a specific dataset.

**Query Parameters**:
- `dataset_id` (required): The dataset identifier to search for

**Response** (200 OK):
```json
{
  "dataset_id": "my-dataset",
  "status": "completed",
  "fingerprint_object": "fingerprints/my-dataset/contract_123.csv",
  "source_url": "http://example.com/contract_123.csv",
  "generated_at": "2025-10-21T14:30:45Z",
  "matches": [
    {
      "dataset_id": "similar-dataset-1",
      "similarity_score": 0.9234,
      "algorithm": "adhoc_minhash",
      "source_url": "http://example.com/contract_456.csv"
    },
    {
      "dataset_id": "similar-dataset-2",
      "similarity_score": 0.7891,
      "algorithm": "adhoc_minhash",
      "source_url": "http://example.com/contract_789.csv"
    }
  ],
  "match_count": 2
}
```

**Response Fields**:
- `dataset_id` - The dataset identifier that was searched
- `status` - Processing status ("completed", "processing", or "not_found")
- `fingerprint_object` - MinIO object path of the fingerprint (if found)
- `source_url` - Original source URL of the fingerprint (if found)
- `generated_at` - ISO 8601 timestamp when results were generated (if found)
- `matches` - Array of similar fingerprints found
- `match_count` - Total number of matches

**Error Responses**:
- `400 Bad Request` - Invalid dataset_id (blank or whitespace-only)
- `404 Not Found` - No similarity results found for the dataset

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

### Similarity Settings
- `SIMILARITY_THRESHOLD` - Minimum similarity score for matches (default: `0.7`, range: 0.0-1.0)

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

## Usage Examples

### Example 1: Submit a Fingerprint for Similarity Analysis

```bash
curl -X POST http://localhost:8000/similarity \
  -H "Content-Type: application/json" \
  -d '{
    "fingerprint_url": "https://storage.example.com/fingerprints/dataset123.json",
    "dataset_id": "dataset-123"
  }'
```

**Response:**
```json
{
  "dataset_id": "dataset-123",
  "fingerprint_url": "https://storage.example.com/fingerprints/dataset123.json",
  "status": "accepted",
  "remote_object_available": true
}
```

### Example 2: Search for Similarity Results

```bash
curl http://localhost:8000/search?dataset_id=dataset-123
```

**Response:**
```json
{
  "dataset_id": "dataset-123",
  "status": "completed",
  "fingerprint_object": "fingerprints/dataset-123/dataset123.json",
  "source_url": "https://storage.example.com/fingerprints/dataset123.json",
  "generated_at": "2025-10-21T14:30:45Z",
  "matches": [
    {
      "dataset_id": "dataset-456",
      "similarity_score": 0.9234,
      "algorithm": "adhoc_minhash",
      "source_url": "https://storage.example.com/fingerprints/dataset456.json"
    }
  ],
  "match_count": 1
}
```

### Example 3: Check Service Health

```bash
curl http://localhost:8000/health
```

**Response:**
```json
{
  "status": "ok"
}
```

## Data Flow

1. Client sends POST request to `/similarity` with fingerprint URL and dataset ID
2. Service validates that dataset_id is non-blank
3. Service probes the remote URL with a HEAD request to confirm accessibility
4. If URL is inaccessible, returns HTTP 404 immediately
5. If URL is accessible, returns HTTP 202 and spawns background thread
6. Background thread:
   - Downloads fingerprint from the URL
   - Stores fingerprint to MinIO at `fingerprints/{dataset_id}/{filename}`
   - Fetches all existing fingerprints from MinIO
   - Computes Jaccard similarity using MinHash signatures
   - Filters matches above the similarity threshold (default: 0.7)
   - Generates similarity result metadata with matched fingerprints
   - Stores metadata to MinIO at `similarity/{dataset_id}/{filename}.json`

## Similarity Computation

### MinHash Algorithm

The service uses **MinHash** fingerprints to efficiently detect similar datasets. Fingerprints are generated by the Airflow DAG (`pistis_fingerprint_dag`) which processes CSV files and creates 128-element MinHash signatures.

**Supported Algorithms**:
- `adhoc_minhash` - Custom MinHash implementation using SHA1 hashing
- `datasketch_minhash` - Implementation using the datasketch library

### Jaccard Similarity

Similarity is computed using the Jaccard similarity coefficient, which estimates how similar two datasets are based on their MinHash signatures:

- **Similarity Score**: Ranges from 0.0 (completely different) to 1.0 (identical)
- **Calculation**: Proportion of matching hash values in the MinHash signatures
- **Default Threshold**: 0.7 (configurable via `SIMILARITY_THRESHOLD` environment variable)

### Configuration

Configure similarity detection behavior:

```bash
# Set minimum similarity score for matches (0.0 to 1.0)
export SIMILARITY_THRESHOLD=0.8

# Higher values (0.9-1.0) = only very similar datasets
# Lower values (0.5-0.7) = more lenient matching
```

### Example Similarity Scores

- **0.95-1.0**: Nearly identical datasets (minor differences)
- **0.80-0.95**: Highly similar datasets (substantial overlap)
- **0.70-0.80**: Moderately similar datasets (significant overlap)
- **Below 0.70**: Low similarity (filtered out by default)

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

### Similarity Result File Format

The similarity result file is a JSON document stored in MinIO that contains metadata about the fingerprint and its similarity matches. The file is generated automatically after a fingerprint is successfully downloaded and stored.

**Example**: For a fingerprint stored at `fingerprints/my-dataset/contract_123.csv`, the similarity result would be stored at `similarity/my-dataset/contract_123.json` with the following structure:

```json
{
  "dataset_id": "my-dataset",
  "fingerprint_object": "fingerprints/my-dataset/contract_123.csv",
  "source_url": "http://example.com/contract_123.csv",
  "generated_at": "2025-10-21T14:30:45Z",
  "status": "completed",
  "matches": []
}
```

**Field Descriptions**:
- `dataset_id` - The dataset identifier provided in the original request
- `fingerprint_object` - The MinIO object path where the fingerprint is stored
- `source_url` - The original URL from which the fingerprint was downloaded
- `generated_at` - ISO 8601 timestamp (UTC) when the result was generated
- `status` - Processing status (always "completed" when file is written)
- `matches` - Array of similarity match objects found by comparing against existing fingerprints

#### Match Object Structure

When similar fingerprints are found, each match in the `matches` array contains:

```json
{
  "dataset_id": "another-dataset",
  "similarity_score": 0.8523,
  "algorithm": "adhoc_minhash",
  "source_url": "http://example.com/other_contract.csv"
}
```

**Match Field Descriptions**:
- `dataset_id` - The dataset identifier of the similar fingerprint
- `similarity_score` - Jaccard similarity score (0.0 to 1.0), where 1.0 means identical
- `algorithm` - The MinHash algorithm used for the matched fingerprint
- `source_url` - The original source URL of the matched fingerprint

**Complete Example with Matches**:

```json
{
  "dataset_id": "my-dataset",
  "fingerprint_object": "fingerprints/my-dataset/contract_123.csv",
  "source_url": "http://example.com/contract_123.csv",
  "generated_at": "2025-10-21T14:30:45Z",
  "status": "completed",
  "matches": [
    {
      "dataset_id": "similar-dataset-1",
      "similarity_score": 0.9234,
      "algorithm": "adhoc_minhash",
      "source_url": "http://example.com/contract_456.csv"
    },
    {
      "dataset_id": "similar-dataset-2",
      "similarity_score": 0.7891,
      "algorithm": "adhoc_minhash",
      "source_url": "http://example.com/contract_789.csv"
    }
  ]
}
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

