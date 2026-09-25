# PhotoMatch

PhotoMatch is a Django face-search demo for SBrT 2026. It runs as one Docker
container on AWS Elastic Beanstalk, stores face embeddings in RDS PostgreSQL
with pgvector, and reads event photos from S3 using short-lived presigned URLs.

For the complete AWS Management Console deployment walkthrough, see
[AWS_DEPLOYMENT.md](./AWS_DEPLOYMENT.md).

## Deployment architecture

- **Elastic Beanstalk:** Django and Gunicorn in one Docker container.
- **RDS PostgreSQL:** source of truth for 128-dimensional face embeddings.
- **S3:** event photos only; the application role is read-only (`s3:GetObject`
  and `s3:ListBucket`).
- **Selfies:** processed in memory for one request and never persisted.

The local `THF_face_database.pkl`, `db.sqlite3`, dataset images, virtualenv,
and model artifacts are intentionally excluded from Git and Docker images.

## Environment variables

Set these in Elastic Beanstalk **Configuration > Updates, monitoring, and
logging > Environment properties** (or with `eb setenv`). Never commit them.

Required:

- `DJANGO_SECRET_KEY`: long random production secret.
- `DJANGO_ALLOWED_HOSTS`: comma-separated hostnames, for example
  `your-env.elasticbeanstalk.com,www.example.com`.
- `DJANGO_CSRF_TRUSTED_ORIGINS`: comma-separated full origins including the
  scheme, for example `https://your-env.elasticbeanstalk.com`.
- `DATABASE_URL`: PostgreSQL URL, for example
  `postgresql://photomatch:password@rds-endpoint:5432/photomatch`.
- `S3_BUCKET`: bucket containing event photos.

Optional:

- `S3_IMAGE_PREFIX`: object prefix, default `dataset/`.
- `MATCH_THRESHOLD`: distance threshold, default `0.60`.
- `DJANGO_DEBUG`: keep `false` in AWS.
- `DJANGO_SECURE_SSL_REDIRECT`: set `true` after HTTPS and the HTTP
  redirect are configured.
- `DJANGO_HSTS_SECONDS`: set to `31536000` only after HTTPS is confirmed.
- `LOCAL_PHOTO_DB_ENABLED`: local PKL fallback, default `true` outside AWS;
  set `false` in AWS.

Use an AWS Secrets Manager or Systems Manager-backed deployment workflow for
database credentials where available. Do not put passwords in source control,
`.ebextensions`, `Dockerrun.aws.json`, or shell history.

## Local development

1. Install dependencies:
   - `pip install -r requirements.txt`
   - If you previously installed dependencies before this update, run the command again so `setuptools` is present (required by `face_recognition_models`).
2. Export environment variables listed above.
3. Run migrations:
   - `python manage.py migrate`
4. (One-time) import PKL shards into Postgres:
   - `python manage.py import_pkl_to_rds --glob "/path/to/shards/*.pkl"`
5. Start the app:
   - `python manage.py runserver 0.0.0.0:8080`

When running outside AWS, the app can use a local photo database automatically if present:
- `LOCAL_PHOTO_DB_ENABLED` (optional, default `true`)
- `LOCAL_PHOTO_DB_PATH` (optional, default `./THF_face_database.pkl`)
- `LOCAL_PHOTO_IMAGES_DIR` (optional, defaults to `DATASET_IMAGES_DIR` or `./dataset_images`)

If S3 is not configured and local mode is active, result previews are served from `/photos/<image_name>`.

## Health check

- `GET /health` returns HTTP 200 JSON for ALB/EB health checks.

## AWS deployment: step by step

The commands below use the AWS CLI, Docker, and the Elastic Beanstalk CLI.
Install and configure them with an IAM deployment identity before starting:

```powershell
aws configure
pip install awsebcli --upgrade --user
```

### 1. Create the S3 bucket and upload photos

Choose a globally unique bucket name in the same AWS Region as Elastic
Beanstalk and RDS. Keep the bucket private; the application generates
presigned GET URLs.

```powershell
aws s3 mb s3://YOUR_PHOTO_BUCKET --region YOUR_REGION
aws s3 sync .\dataset s3://YOUR_PHOTO_BUCKET/dataset/ --only-show-errors
```

Do not enable public access for this bucket. Do not give the application
`PutObject` or `DeleteObject` permissions.

### 2. Create RDS PostgreSQL

In the RDS console:

1. Create a PostgreSQL DB instance in `YOUR_REGION`.
2. Put it in the same VPC as the Elastic Beanstalk environment.
3. Use private subnets where possible and disable public access unless a
   controlled migration path requires it.
4. Create a database named `photomatch` and a dedicated application user.
5. Attach an RDS security group that allows TCP `5432` **only from the
   Elastic Beanstalk instance security group**.
6. Enable encryption at rest, automated backups, and deletion protection for
   a production event.

After the instance is available, connect through an approved network path
(for example a bastion, VPN, or AWS CloudShell where the VPC permits access)
and enable pgvector:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

The extension is named `vector` in PostgreSQL. Confirm that the selected RDS
PostgreSQL engine version supports it before creating the database.

### 3. Create the Elastic Beanstalk application

From the repository root:

```powershell
eb init photomatch --platform docker --region YOUR_REGION
```

When prompted, choose the existing AWS key pair only if you need SSH
troubleshooting access. Otherwise, use the least-privileged setup available.

Create the environment:

```powershell
eb create photomatch-prod --instance_type t3.small
```

This repository contains a `Dockerfile`; Elastic Beanstalk builds and runs
that single container and exposes port `8080`. The
`.ebextensions/01-environment.config` file configures a load-balanced
environment and the health path as `/health`. This is a single-container
deployment, not a single-instance deployment.

For a temporary demo you may choose a single-instance environment in the
console, but it has less availability and should not be used for a busy event.

### 4. Configure the S3 instance-role permissions

Attach a least-privilege inline policy to the Elastic Beanstalk EC2 instance
profile role. Replace the bucket and prefix:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::YOUR_PHOTO_BUCKET",
      "Condition": {
        "StringLike": {"s3:prefix": ["dataset", "dataset/*"]}
      }
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::YOUR_PHOTO_BUCKET/dataset/*"
    }
  ]
}
```

The application does not need S3 write permissions. The default Elastic
Beanstalk service role and EC2 instance profile are separate roles; attach
this policy to the **EC2 instance profile role**, not the service role.

### 5. Set production environment properties

Generate a secret locally without printing it to source control:

```powershell
$secret = & ".\.venv\Scripts\python.exe" -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
eb setenv `
  DJANGO_SECRET_KEY="$secret" `
  DJANGO_DEBUG=false `
  DJANGO_ALLOWED_HOSTS="YOUR_ENV.elasticbeanstalk.com" `
  DJANGO_CSRF_TRUSTED_ORIGINS="https://YOUR_ENV.elasticbeanstalk.com" `
  DATABASE_URL="postgresql://DB_USER:DB_PASSWORD@RDS_ENDPOINT:5432/photomatch" `
  S3_BUCKET="YOUR_PHOTO_BUCKET" `
  S3_IMAGE_PREFIX="dataset/" `
  LOCAL_PHOTO_DB_ENABLED=false `
  DJANGO_SECURE_SSL_REDIRECT=false `
  DJANGO_HSTS_SECONDS=0
```

Prefer setting `DATABASE_URL` through a secrets-aware process rather than
putting a real password in a terminal command. If your password contains
special URL characters, URL-encode it.

### 6. Deploy and run migrations

```powershell
eb deploy photomatch-prod
eb health photomatch-prod
eb open photomatch-prod
```

Run the production checks and database migrations in the deployed
environment. Use an approved SSH/SSM path to the instance, then:

```bash
python manage.py check --deploy
python manage.py migrate --noinput
```

If the environment is private, run these commands from a maintenance shell
with the same container image and environment variables. Do not run
migrations concurrently from multiple instances.

### 7. Import the face database into RDS

The PKL file is not deployed with the web container. From a machine that can
reach the RDS endpoint, run:

```powershell
python manage.py import_pkl_to_rds --glob "C:\path\to\THF_face_database.pkl"
```

Verify the import:

```sql
SELECT COUNT(*) FROM search_faceembedding;
```

For a large import, use a controlled one-off migration job rather than
running the import during every web deployment.

### 8. Verify the live service

Check all of the following before sharing the QR code:

1. `https://YOUR_HOST/health` returns `{"status":"ok"}`.
2. The home page loads without a 500 response.
3. A test selfie returns matches or the expected no-match state.
4. Result images load from presigned S3 URLs.
5. S3 objects are still private and direct unauthenticated object URLs fail.
6. RDS accepts connections only from the Beanstalk security group.
7. Logs show no database password, selfie bytes, or unexpected S3 errors.

Useful commands:

```powershell
eb logs --all
eb status
eb events
```

### 9. Add HTTPS and a custom domain

For a real event URL, request an ACM certificate in the region required by
your load balancer, validate the domain, attach the certificate to the
Beanstalk load balancer's HTTPS listener, and redirect HTTP to HTTPS. Add
both the custom hostname to `DJANGO_ALLOWED_HOSTS` and its full HTTPS origin
to `DJANGO_CSRF_TRUSTED_ORIGINS`.
After HTTPS is working, set `DJANGO_SECURE_SSL_REDIRECT=true` and
`DJANGO_HSTS_SECONDS=31536000`, then redeploy.

### Official references

- [Elastic Beanstalk Docker environments](https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/create_deploy_docker.html)
- [Elastic Beanstalk instance profiles](https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/iam-instanceprofile.html)
- [RDS PostgreSQL extensions](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Appendix.PostgreSQL.CommonDBATasks.Extensions.html)
- [S3 IAM policy actions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-with-s3-actions.html)
- [Django deployment checklist](https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/)
