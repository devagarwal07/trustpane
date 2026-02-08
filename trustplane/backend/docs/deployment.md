# Deployment Guide

## Overview

TrustPlane supports multiple deployment strategies:

1. **Docker Compose** - Local development & small deployments
2. **Kubernetes** - Production-grade orchestration
3. **Cloud Platforms** - AWS, Azure, GCP
4. **CI/CD** - Automated GitHub Actions pipeline

## Quick Start with Docker

### Prerequisites

- Docker 24.0+
- Docker Compose 2.20+
- 4GB+ RAM
- 10GB+ disk space

### Local Development

```bash
# Clone repository
git clone https://github.com/yourusername/trustplane.git
cd trustplane

# Create .env file
cp backend/.env.example backend/.env

# Edit .env with your Supabase credentials
nano backend/.env

# Start services
docker-compose up -d

# View logs
docker-compose logs -f backend

# Access API
curl http://localhost:8000/health
```

### Environment Variables

Create `backend/.env`:

```env
# Application
PROJECT_NAME=TrustPlane
VERSION=1.0.0
DEBUG=false
ENVIRONMENT=production
API_V1_PREFIX=/api/v1

# Security
SECRET_KEY=your-super-secret-key-min-32-chars
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
SUPABASE_JWT_SECRET=your-jwt-secret

# CORS
ALLOWED_ORIGINS=https://app.trustplane.com,https://staging.trustplane.com

# Redis (optional)
REDIS_URL=redis://redis:6379/0

# Monitoring (optional)
SENTRY_DSN=https://your-sentry-dsn
```

### Production with Nginx

```bash
# Start with Nginx reverse proxy
docker-compose --profile production up -d

# This starts:
# - Backend API (4 workers)
# - Redis cache
# - Nginx reverse proxy with SSL
```

## Kubernetes Deployment

### Prerequisites

- Kubernetes 1.24+
- kubectl configured
- Helm 3.0+ (optional)

### Deploy with kubectl

```bash
# Create namespace
kubectl create namespace trustplane

# Create secrets
kubectl create secret generic trustplane-secrets \
  --from-literal=SECRET_KEY=your-secret-key \
  --from-literal=SUPABASE_URL=your-url \
  --from-literal=SUPABASE_KEY=your-key \
  --from-literal=SUPABASE_JWT_SECRET=your-jwt-secret \
  -n trustplane

# Deploy backend
kubectl apply -f k8s/backend-deployment.yaml -n trustplane
kubectl apply -f k8s/backend-service.yaml -n trustplane

# Deploy Redis
kubectl apply -f k8s/redis-deployment.yaml -n trustplane
kubectl apply -f k8s/redis-service.yaml -n trustplane

# Deploy Ingress
kubectl apply -f k8s/ingress.yaml -n trustplane

# Check status
kubectl get pods -n trustplane
kubectl get services -n trustplane
```

### Example Kubernetes Manifests

**backend-deployment.yaml:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: trustplane-backend
  labels:
    app: trustplane
    component: backend
spec:
  replicas: 3
  selector:
    matchLabels:
      app: trustplane
      component: backend
  template:
    metadata:
      labels:
        app: trustplane
        component: backend
    spec:
      containers:
      - name: backend
        image: ghcr.io/yourusername/trustplane-backend:latest
        ports:
        - containerPort: 8000
        env:
        - name: SECRET_KEY
          valueFrom:
            secretKeyRef:
              name: trustplane-secrets
              key: SECRET_KEY
        - name: SUPABASE_URL
          valueFrom:
            secretKeyRef:
              name: trustplane-secrets
              key: SUPABASE_URL
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
```

## Cloud Platform Deployment

### AWS (Elastic Beanstalk)

```bash
# Install EB CLI
pip install awsebcli

# Initialize
cd backend
eb init -p docker trustplane

# Create environment
eb create trustplane-prod --database --database.engine postgres

# Deploy
eb deploy

# Open application
eb open
```

### AWS (ECS Fargate)

```bash
# Create ECR repository
aws ecr create-repository --repository-name trustplane-backend

# Build and push image
docker build -t trustplane-backend backend/
docker tag trustplane-backend:latest <account>.dkr.ecr.<region>.amazonaws.com/trustplane-backend:latest
docker push <account>.dkr.ecr.<region>.amazonaws.com/trustplane-backend:latest

# Create ECS cluster and service
aws ecs create-cluster --cluster-name trustplane-cluster
# Use AWS Console or CloudFormation for service creation
```

### Azure (Container Apps)

```bash
# Login to Azure
az login

# Create resource group
az group create --name trustplane-rg --location eastus

# Create container app environment
az containerapp env create \
  --name trustplane-env \
  --resource-group trustplane-rg \
  --location eastus

# Deploy container app
az containerapp create \
  --name trustplane-backend \
  --resource-group trustplane-rg \
  --environment trustplane-env \
  --image ghcr.io/yourusername/trustplane-backend:latest \
  --target-port 8000 \
  --ingress external \
  --env-vars \
    SECRET_KEY=secretref:secret-key \
    SUPABASE_URL=secretref:supabase-url
```

### GCP (Cloud Run)

```bash
# Enable Cloud Run API
gcloud services enable run.googleapis.com

# Deploy
gcloud run deploy trustplane-backend \
  --image ghcr.io/yourusername/trustplane-backend:latest \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars SECRET_KEY=your-secret \
  --set-env-vars SUPABASE_URL=your-url
```

## CI/CD with GitHub Actions

### Setup

1. **Configure Secrets** in GitHub repository settings:
   - `SUPABASE_URL`
   - `SUPABASE_KEY`
   - `SUPABASE_JWT_SECRET`
   - `SECRET_KEY`

2. **Push to trigger CI/CD**:

```bash
git add .
git commit -m "Deploy to production"
git push origin main
```

### Pipeline Stages

1. **Lint** - Code quality checks (Black, isort, Flake8)
2. **Test** - Run test suite with coverage
3. **Security** - Vulnerability scanning (Trivy, Bandit)
4. **Build** - Build and push Docker image
5. **Deploy Staging** - Auto-deploy develop branch
6. **Deploy Production** - Auto-deploy main branch

### Manual Deployment

Trigger manual deployment:

```bash
# Via GitHub CLI
gh workflow run ci-cd.yml

# Via API
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  https://api.github.com/repos/OWNER/REPO/actions/workflows/ci-cd.yml/dispatches \
  -d '{"ref":"main"}'
```

## Production Checklist

### Security

- [ ] Change `SECRET_KEY` from default
- [ ] Use strong Supabase credentials
- [ ] Enable HTTPS/TLS
- [ ] Configure CORS for specific domains
- [ ] Enable rate limiting
- [ ] Set up WAF/DDoS protection
- [ ] Configure security headers
- [ ] Enable audit logging

### Performance

- [ ] Configure Redis for caching
- [ ] Enable gzip compression
- [ ] Set up CDN for static assets
- [ ] Configure connection pooling
- [ ] Optimize database queries
- [ ] Enable query caching
- [ ] Configure horizontal scaling

### Monitoring

- [ ] Set up health checks
- [ ] Configure log aggregation (ELK, CloudWatch)
- [ ] Enable APM (Sentry, DataDog, New Relic)
- [ ] Set up uptime monitoring
- [ ] Configure alerting (PagerDuty, Slack)
- [ ] Create dashboards (Grafana)
- [ ] Enable distributed tracing

### Backup & Recovery

- [ ] Configure database backups
- [ ] Set up backup retention policy
- [ ] Test restore procedures
- [ ] Document disaster recovery plan
- [ ] Set up multi-region redundancy
- [ ] Configure data replication

### Scaling

- [ ] Configure auto-scaling rules
- [ ] Set up load balancer
- [ ] Enable horizontal pod autoscaling (K8s)
- [ ] Configure database read replicas
- [ ] Set up job queues for async tasks
- [ ] Enable cache warming

## Monitoring & Troubleshooting

### Health Checks

```bash
# Basic health check
curl https://api.trustplane.com/health

# Detailed status (requires auth)
curl -H "Authorization: Bearer $TOKEN" \
  https://api.trustplane.com/api/v1/admin/status
```

### Logs

```bash
# Docker Compose
docker-compose logs -f backend

# Kubernetes
kubectl logs -f deployment/trustplane-backend -n trustplane

# Follow all pods
kubectl logs -f -l app=trustplane -n trustplane

# AWS CloudWatch
aws logs tail /aws/ecs/trustplane-backend --follow

# Azure
az containerapp logs show \
  --name trustplane-backend \
  --resource-group trustplane-rg \
  --follow
```

### Metrics

```bash
# Prometheus metrics endpoint
curl https://api.trustplane.com/metrics

# Health check with details
curl https://api.trustplane.com/health?detailed=true
```

### Common Issues

**Issue: Container fails to start**

```bash
# Check logs
docker-compose logs backend

# Check environment variables
docker-compose exec backend env | grep SUPABASE

# Verify connectivity
docker-compose exec backend curl https://your-project.supabase.co
```

**Issue: High memory usage**

```bash
# Check resource usage
docker stats

# Reduce workers
# In Dockerfile: CMD ["uvicorn", "app.main:app", "--workers", "2"]
```

**Issue: Rate limiting too strict**

```python
# In app/core/rate_limiting.py
DEFAULT_IP_RATE_LIMIT = RateLimitConfig(
    requests=200,  # Increase from 100
    window_seconds=60
)
```

## Rollback Procedures

### Docker

```bash
# List images
docker images

# Deploy previous version
docker-compose down
docker-compose up -d --build trustplane-backend:v1.2.3
```

### Kubernetes

```bash
# View deployment history
kubectl rollout history deployment/trustplane-backend -n trustplane

# Rollback to previous version
kubectl rollout undo deployment/trustplane-backend -n trustplane

# Rollback to specific revision
kubectl rollout undo deployment/trustplane-backend --to-revision=2 -n trustplane
```

### Cloud Platforms

```bash
# AWS ECS
aws ecs update-service \
  --cluster trustplane-cluster \
  --service trustplane-backend \
  --task-definition trustplane-backend:5

# Azure Container Apps
az containerapp revision list \
  --name trustplane-backend \
  --resource-group trustplane-rg

az containerapp revision activate \
  --revision <previous-revision-name>
```

## Performance Tuning

### Database Optimization

```python
# Connection pooling
SUPABASE_POOL_SIZE=20
SUPABASE_MAX_OVERFLOW=10
```

### Worker Configuration

```bash
# Calculate workers
workers = (2 * CPU_CORES) + 1

# For 4 cores: 9 workers
CMD ["uvicorn", "app.main:app", "--workers", "9"]
```

### Redis Caching

```python
# Enable Redis for rate limiting and caching
REDIS_URL=redis://redis:6379/0
CACHE_TTL=300  # 5 minutes
```

## Support & Resources

- **Documentation**: https://docs.trustplane.com
- **Status Page**: https://status.trustplane.com
- **Support**: support@trustplane.com
- **GitHub**: https://github.com/yourusername/trustplane
