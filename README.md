# Lead Machine

A self-hosted email scraping, verification, and warmup system built with Python and FastAPI.

## Features

- **Website Scraping**: Crawl websites to extract email addresses with metadata (name, role, phone)
- **Email Verification**: 5-step verification without paid APIs (syntax, disposable, MX, SMTP, catch-all)
- **GHL Integration**: Push verified leads to GoHighLevel CRM
- **Email Warmup**: Automated sender reputation building system
- **n8n Compatible**: Designed to work with n8n automation workflows

## Quick Start

### 1. Clone and Configure

```bash
git clone https://github.com/bensblueprints/lead-machine.git
cd lead-machine
cp .env.example .env
# Edit .env with your settings
```

### 2. Run with Docker

```bash
docker-compose up -d
```

The API will be available at `http://localhost:8000`

### 3. Verify Installation

```bash
curl http://localhost:8000/api/health
```

## API Endpoints

All endpoints require `X-API-Key` header.

### POST /api/scrape

Scrape domains for email addresses, verify them, and push to GHL.

**Single domain:**
```bash
curl -X POST http://localhost:8000/api/scrape \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"domain": "example.com"}'
```

**Multiple domains:**
```bash
curl -X POST http://localhost:8000/api/scrape \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"domains": ["example.com", "another.com"]}'
```

**Response:**
```json
{
  "success": true,
  "domain": "example.com",
  "summary": {
    "pages_crawled": 8,
    "emails_found": 5,
    "emails_valid": 3,
    "emails_pushed_to_ghl": 3
  },
  "leads": [
    {
      "email": "john@example.com",
      "name": "John Smith",
      "role": "CEO",
      "phone": "+1-555-123-4567",
      "source_url": "https://example.com/about",
      "verification": {
        "status": "valid",
        "confidence": 95,
        "is_catch_all": false,
        "is_free_provider": false
      },
      "ghl": {
        "pushed": true,
        "contact_id": "ghl_abc123"
      }
    }
  ]
}
```

### POST /api/verify

Verify email addresses independently.

```bash
curl -X POST http://localhost:8000/api/verify \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com"}'
```

**Multiple emails:**
```bash
curl -X POST http://localhost:8000/api/verify \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"emails": ["test1@example.com", "test2@example.com"]}'
```

### POST /api/warmup/start

Start email warmup for an account.

```bash
curl -X POST http://localhost:8000/api/warmup/start \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "sender@yourdomain.com",
    "smtp_host": "smtp.yourdomain.com",
    "smtp_port": 587,
    "smtp_username": "sender@yourdomain.com",
    "smtp_password": "your-password",
    "imap_host": "imap.yourdomain.com",
    "imap_port": 993,
    "imap_username": "sender@yourdomain.com",
    "imap_password": "your-password"
  }'
```

### POST /api/warmup/stop

Stop warmup for an account.

```bash
curl -X POST http://localhost:8000/api/warmup/stop \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"email": "sender@yourdomain.com"}'
```

### GET /api/warmup/status

Get warmup status for all accounts.

```bash
curl http://localhost:8000/api/warmup/status \
  -H "X-API-Key: your-api-key"
```

### GET /api/health

Health check endpoint.

```bash
curl http://localhost:8000/api/health
```

## n8n Integration

### Setting up n8n to use Lead Machine

1. **Add HTTP Request node** after your Google Places Search node
2. **Configure the node:**
   - Method: POST
   - URL: `http://lead-machine:8000/api/scrape`
   - Headers: `X-API-Key: your-api-key`
   - Body: `{"domain": "{{ $json.website }}"}`

3. **Process the response** to get verified emails

### Example n8n Workflow

```
[Google Places Search] → [Extract Website] → [Lead Machine /api/scrape] → [Filter Valid Emails] → [Save to Database]
```

## Email Verification Confidence Scores

| Status | Confidence | Description |
|--------|------------|-------------|
| Valid + No Catch-all | 95% | Email definitely exists |
| Valid + Catch-all | 50% | Domain accepts all emails |
| Unknown | 30-40% | Could not verify |
| Invalid | 0% | Email does not exist |

## Warmup Schedule

| Week | Daily Emails |
|------|-------------|
| 1 | 5 |
| 2 | 10 |
| 3 | 15 |
| 4 | 20 |
| 5 | 30 |
| 6+ | 40 |

## Environment Variables

See `.env.example` for all configuration options.

## Architecture

```
lead-machine/
├── app/
│   ├── api/           # API routes
│   ├── core/          # Configuration
│   ├── models/        # Database models
│   ├── modules/       # Core modules
│   │   ├── verifier.py    # Email verification
│   │   ├── scraper.py     # Website scraping
│   │   ├── ghl.py         # GHL integration
│   │   └── warmup.py      # Warmup system
│   ├── main.py        # FastAPI app
│   └── worker.py      # Background worker
├── data/              # SQLite database
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

## Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run locally
uvicorn app.main:app --reload --port 8000
```

## License

MIT
