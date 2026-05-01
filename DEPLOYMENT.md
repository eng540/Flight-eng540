# Flight Intelligence - Deployment Guide

## Quick Deployment Options

### Option 1: Docker Compose (Recommended for Local/Server)

```bash
# Clone and navigate
cd flight-intelligence/docker

# Start all services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f
```

Services will be available at:
- Frontend: http://localhost
- Backend API: http://localhost:8000
- API Documentation: http://localhost:8000/docs

### Option 2: Railway (Cloud Deployment)

1. **Install Railway CLI**:
```bash
npm install -g @railway/cli
```

2. **Login and initialize**:
```bash
railway login
railway init
```

3. **Create services**:
```bash
# Create PostgreSQL database
railway add --database postgres

# Create Redis
railway add --database redis

# Deploy backend
railway up --service backend

# Deploy worker
railway up --service worker

# Deploy scheduler
railway up --service scheduler

# Deploy frontend
railway up --service frontend
```

4. **Set environment variables**:
```bash
railway variables set DATABASE_URL="postgresql://..."
railway variables set REDIS_URL="redis://..."
railway variables set OPENSKY_USERNAME="your_username"
railway variables set OPENSKY_PASSWORD="your_password"
```

### Option 3: Manual Deployment

#### Backend

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DATABASE_URL="postgresql://user:pass@localhost:5432/flight_intelligence"
export REDIS_URL="redis://localhost:6379/0"

# Run migrations
alembic upgrade head

# Start server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

#### Worker

```bash
cd worker

# Start Celery worker
celery -A celery_app worker -l info -Q ingestion,maintenance,default

# Start Celery beat (scheduler) - in another terminal
celery -A celery_app beat -l info
```

#### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Build for production
npm run build

# Serve with Nginx or any static server
# The dist/ folder contains the built application
```

## Environment Variables

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://user:pass@host:5432/dbname` |
| `REDIS_URL` | Redis connection string | `redis://host:6379/0` |

### Optional

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENSKY_USERNAME` | OpenSky API username | - |
| `OPENSKY_PASSWORD` | OpenSky API password | - |
| `OPENSKY_CLIENT_ID` | OpenSky OAuth client ID | - |
| `OPENSKY_CLIENT_SECRET` | OpenSky OAuth client secret | - |
| `DEBUG` | Enable debug mode | `false` |
| `SECRET_KEY` | Application secret key | `change-me` |

## Database Setup

### PostgreSQL

```sql
-- Create database
CREATE DATABASE flight_intelligence;

-- Create user (optional)
CREATE USER flight_user WITH PASSWORD 'secure_password';
GRANT ALL PRIVILEGES ON DATABASE flight_intelligence TO flight_user;
```

### Migrations

```bash
# Run migrations
cd backend
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "description"

# Rollback
alembic downgrade -1
```

## Monitoring

### Health Checks

- API Health: `GET /health`
- Database Health: `GET /stats/health`

### Logs

```bash
# Docker logs
docker-compose logs -f backend
docker-compose logs -f worker
docker-compose logs -f scheduler

# Celery Flower (optional)
cd worker
celery -A celery_app flower --port=5555
```

## Troubleshooting

### Database Connection Issues

1. Check PostgreSQL is running:
```bash
docker-compose ps db
```

2. Verify connection string:
```bash
psql $DATABASE_URL -c "SELECT 1"
```

### Worker Not Processing Tasks

1. Check Redis connection:
```bash
redis-cli -u $REDIS_URL ping
```

2. Verify worker is running:
```bash
docker-compose ps worker
```

3. Check Celery logs:
```bash
docker-compose logs worker
```

### API Not Responding

1. Check container status:
```bash
docker-compose ps backend
```

2. View logs:
```bash
docker-compose logs backend
```

3. Test health endpoint:
```bash
curl http://localhost:8000/health
```

## Scaling

### Horizontal Scaling

```yaml
# docker-compose.yml
services:
  backend:
    deploy:
      replicas: 3
  
  worker:
    deploy:
      replicas: 2
```

### Database Optimization

- Add read replicas for heavy read workloads
- Use connection pooling (PgBouncer)
- Add indexes for frequently queried fields

## Security

1. **Change default passwords**
2. **Use HTTPS in production**
3. **Set strong SECRET_KEY**
4. **Enable firewall rules**
5. **Regular security updates**

## Backup & Recovery

### Database Backup

```bash
# Backup
pg_dump $DATABASE_URL > backup_$(date +%Y%m%d).sql

# Restore
psql $DATABASE_URL < backup_20240101.sql
```

### Automated Backups

```bash
# Add to crontab (daily at 2 AM)
0 2 * * * pg_dump $DATABASE_URL | gzip > /backups/flights_$(date +\%Y\%m\%d).sql.gz
```

## Support

For issues and questions:
- Check logs: `docker-compose logs`
- Review documentation: `/docs`
- Open an issue on GitHub
