# Flight Intelligence Platform - Makefile

.PHONY: help install dev build test clean docker-up docker-down deploy

# Default target
help:
	@echo "Flight Intelligence Platform - Available Commands:"
	@echo ""
	@echo "  make install      - Install all dependencies"
	@echo "  make dev          - Start development servers"
	@echo "  make build        - Build production images"
	@echo "  make test         - Run all tests"
	@echo "  make docker-up    - Start Docker services"
	@echo "  make docker-down  - Stop Docker services"
	@echo "  make clean        - Clean build artifacts"
	@echo "  make deploy       - Deploy to production"
	@echo ""

# Installation
install:
	@echo "Installing backend dependencies..."
	cd backend && pip install -r requirements.txt
	@echo "Installing frontend dependencies..."
	cd frontend && npm install

# Development
dev:
	@echo "Starting development servers..."
	@echo "Backend: http://localhost:8000"
	@echo "Frontend: http://localhost:5173"
	@make dev-backend & make dev-frontend

dev-backend:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

# Build
build:
	@echo "Building production images..."
	cd docker && docker-compose build

# Testing
test:
	@echo "Running backend tests..."
	cd backend && pytest -v

test-coverage:
	cd backend && pytest --cov=app --cov-report=html

# Docker
docker-up:
	@echo "Starting Docker services..."
	cd docker && docker-compose up -d

docker-down:
	@echo "Stopping Docker services..."
	cd docker && docker-compose down

docker-logs:
	cd docker && docker-compose logs -f

docker-build:
	cd docker && docker-compose build --no-cache

# Database
db-migrate:
	cd backend && alembic upgrade head

db-rollback:
	cd backend && alembic downgrade -1

db-reset:
	cd backend && alembic downgrade base && alembic upgrade head

# Worker
worker:
	cd worker && celery -A celery_app worker -l info -Q ingestion,maintenance,default

scheduler:
	cd worker && celery -A celery_app beat -l info

flower:
	cd worker && celery -A celery_app flower

# Cleaning
clean:
	@echo "Cleaning build artifacts..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	cd frontend && rm -rf dist node_modules 2>/dev/null || true

# Deployment
deploy:
	@echo "Deploying to production..."
	@echo "Please ensure all environment variables are set"
	cd docker && docker-compose -f docker-compose.yml up -d

# Linting
lint:
	cd backend && flake8 app --max-line-length=120
	cd frontend && npm run lint

# Format
format:
	cd backend && black app --line-length=120
	cd frontend && npm run format

# All-in-one commands
setup: install db-migrate
	@echo "Setup complete!"

start: docker-up
	@echo "Services started!"
	@echo "Frontend: http://localhost"
	@echo "API: http://localhost:8000"
	@echo "API Docs: http://localhost:8000/docs"

stop: docker-down
	@echo "Services stopped!"
