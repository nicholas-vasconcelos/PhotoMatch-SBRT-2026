# PhotoMatch AWS Deployment Guide

This guide deploys PhotoMatch using the AWS web console. It assumes:

- PhotoMatch runs as one Docker container on Elastic Beanstalk.
- Face embeddings are stored in Amazon RDS for PostgreSQL with `pgvector`.
- Event photos are private objects in Amazon S3.
- Selfies are processed in memory for one request and are never persisted.

The deployment should use one AWS Region for the S3 bucket, RDS database,
Elastic Beanstalk application, and supporting networking whenever possible.

## Before you begin

Install Docker Desktop if you want to build and test the image locally. Docker
is not required for the AWS Console upload if Elastic Beanstalk builds the
repository's `Dockerfile`, but local testing is strongly recommended.

Confirm that the repository contains:

- `Dockerfile`
- `requirements.txt`
- `.dockerignore`
- `.ebextensions/01-environment.config`
- `manage.py`
- `photomatch/`
- `search/`

Do not upload or commit these local-only files:

- `.env`
- `.venv/`
- `db.sqlite3`
- `THF_face_database.pkl`
- local photo datasets
- private keys or passwords

The repository's `.gitignore` and `.dockerignore` exclude these artifacts.

## 1. Create or choose an AWS Region

1. Sign in to the [AWS Management Console](https://console.aws.amazon.com/).
2. Select a Region near the event attendees.
3. Use that same Region for S3, RDS, Elastic Beanstalk, and ACM.

The AWS Console changes slightly over time. If a menu is in a different
location, use the console search bar for the service name.

## 2. Create a private S3 photo bucket

1. Open **Amazon S3**.
2. Choose **Create bucket**.
3. Enter a globally unique bucket name, for example:
   `photomatch-sbrt2026-photos-ACCOUNT_ID`.
4. Select the deployment Region.
5. Keep **Block all public access** enabled.
6. Keep **ACLs disabled** / **Bucket owner enforced**.
7. Enable versioning if you need accidental-deletion recovery.
8. Enable default encryption.
9. Choose **Create bucket**.

Create the object prefix used by the application:

1. Open the bucket.
2. Choose **Create folder**.
3. Name it `dataset`.
4. Upload the event photos into that folder.

The application expects:

```text
s3://YOUR_PHOTO_BUCKET/dataset/photo-name.jpg
```

Do not make the bucket or objects public. PhotoMatch generates short-lived
presigned GET URLs for matched photos.

## 3. Create security groups

Create two security groups in the VPC that will host the application and
database.

### Elastic Beanstalk security group

1. Open **EC2**.
2. Choose **Security Groups**.
3. Choose **Create security group**.
4. Name it something such as `photomatch-beanstalk-sg`.
5. Allow outbound traffic required for the application.
6. Do not add a database inbound rule here.

### RDS security group

1. Choose **Create security group** again.
2. Name it something such as `photomatch-rds-sg`.
3. Add an inbound rule:
   - **Type:** PostgreSQL
   - **Protocol:** TCP
   - **Port:** `5432`
   - **Source:** the `photomatch-beanstalk-sg` security group
4. Do not allow `0.0.0.0/0` on port `5432`.

The RDS rule must reference the Beanstalk security group, not a broad IP
range. This allows application instances to reach PostgreSQL while keeping
the database private.

## 4. Create the RDS PostgreSQL database

1. Open **Amazon RDS**.
2. Choose **Databases** and then **Create database**.
3. Select **Standard create**.
4. Choose **PostgreSQL**.
5. Select an engine version that supports the `vector` extension.
6. Choose a production-sized instance appropriate for the expected event load.
   A small burstable instance can be used for a temporary demo.
7. Set:
   - **DB instance identifier:** `photomatch-prod`
   - A strong master username
   - A strong master password
   - Initial database name: `photomatch`
8. Under connectivity:
   - Select the same VPC intended for Elastic Beanstalk.
   - Prefer private subnets.
   - Set **Public access** to **No**.
   - Attach `photomatch-rds-sg`.
9. Enable encryption, automated backups, and deletion protection for a
   production event.
10. Choose **Create database**.

Wait until the database status is **Available**. Copy the RDS endpoint from
the database's **Connectivity & security** tab. Do not copy the port into the
hostname; the port is normally `5432`.

### Enable pgvector

Connect through an approved private network path, such as a bastion host,
VPN, or another client that can reach the RDS VPC. Then run:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

The PostgreSQL extension is named `vector`, even though the project commonly
refers to it as pgvector.

If the extension is unavailable, check the RDS PostgreSQL engine version and
the supported extensions for that version before continuing.

## 5. Create the Elastic Beanstalk application

1. Open **Elastic Beanstalk**.
2. Choose **Create application**.
3. Set:
   - **Application name:** `photomatch`
   - **Environment tier:** Web server environment
   - **Environment name:** `photomatch-prod`
4. For the platform, choose:
   - **Platform:** Docker
   - **Platform branch:** the current supported Docker branch shown by AWS
   - **Platform version:** Recommended
5. For application code, choose **Upload your code**.

## 6. Create the deployment ZIP from the repository

Elastic Beanstalk's web upload expects a ZIP containing the project files at
the ZIP root. Do not ZIP the parent folder itself.

The ZIP should contain entries similar to:

```text
Dockerfile
requirements.txt
manage.py
photomatch/
search/
templates/
.ebextensions/
```

Exclude:

```text
.git/
.venv/
db.sqlite3
.env
*.pkl
dataset/
dataset_images/
models/
```

Use the repository's `.dockerignore` as a second protection, but still keep
secrets and large local datasets out of the upload ZIP.

## 7. Upload the application in Elastic Beanstalk

1. In the Elastic Beanstalk creation wizard, choose **Upload your code**.
2. Choose **Local file**.
3. Select the deployment ZIP.
4. Enter a version label such as `photomatch-initial`.
5. Continue to the environment configuration.

Elastic Beanstalk will build the repository's `Dockerfile`. The container
listens on port `8080`, and the existing
`.ebextensions/01-environment.config` configures `/health` as the health
check path. The `.platform/nginx/conf.d/01-upload-size.conf` file allows
request bodies up to 10 MB, while the browser resizes camera selfies to a
maximum dimension of 1280 pixels before upload.

## 8. Configure the environment and networking

In the Elastic Beanstalk wizard, open **Configure more options**.

### Presets and capacity

For an event with multiple attendees, choose a load-balanced environment.
Use a single-instance environment only for a short private test because it
has lower availability.

### Instances and security

Configure:

- The VPC used by RDS.
- Public subnets for the load balancer if the site must be publicly reachable.
- Private subnets for application instances where your network design allows.
- `photomatch-beanstalk-sg` for the EC2 instances.
- An Elastic Beanstalk EC2 instance profile.

The instances need outbound access to:

- RDS
- S3
- Package/image services required during deployment

### Load balancer

Use an Application Load Balancer for a public web deployment. Confirm that
the default process listens on port `8080` and that the health check path is:

```text
/health
```

## 9. Give the Beanstalk EC2 role read-only S3 access

After the environment is created, identify the EC2 instance profile role:

1. Open **Elastic Beanstalk** and select the environment.
2. Open **Configuration**.
3. Open **Security** or the instance profile details.
4. Follow the role link to **IAM**.

Create and attach a customer-managed or inline policy to the **EC2 instance
profile role**. Replace the bucket name and prefix:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::YOUR_PHOTO_BUCKET",
      "Condition": {
        "StringLike": {
          "s3:prefix": ["dataset", "dataset/*"]
        }
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

Do not attach `s3:PutObject` or `s3:DeleteObject`. Do not attach broad
`AmazonS3FullAccess`.

The Elastic Beanstalk service role and the EC2 instance profile role are
different roles. The application needs this S3 policy on the EC2 instance
profile role.

## 10. Configure environment variables in the web console

In the Elastic Beanstalk environment:

1. Open **Configuration**.
2. Find **Updates, monitoring, and logging** or **Software**.
3. Choose **Edit**.
4. Add the following environment properties.
5. Choose **Apply**.

Required properties:

| Name | Value |
| --- | --- |
| `DJANGO_DEBUG` | `false` |
| `DJANGO_SECRET_KEY` | A long random secret |
| `DJANGO_ALLOWED_HOSTS` | `YOUR_ENV.elasticbeanstalk.com` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://YOUR_ENV.elasticbeanstalk.com` |
| `DATABASE_URL` | `postgresql://USER:PASSWORD@RDS_ENDPOINT:5432/photomatch` |
| `S3_BUCKET` | Your private S3 bucket name |
| `S3_IMAGE_PREFIX` | `dataset/` |
| `S3_THUMBNAIL_PREFIX` | `thumb/` |
| `LOCAL_PHOTO_DB_ENABLED` | `false` |

Optional properties:

| Name | Suggested value |
| --- | --- |
| `MATCH_THRESHOLD` | `0.60` |
| `DJANGO_SECURE_SSL_REDIRECT` | `false` until HTTPS is working |
| `DJANGO_HSTS_SECONDS` | `0` until HTTPS is working |

Generate `DJANGO_SECRET_KEY` with a secure password generator. Never commit
it or place it in the ZIP file.

For better production security, store database credentials in AWS Secrets
Manager or Systems Manager Parameter Store and inject them through your
deployment process. If you enter a database URL directly, URL-encode special
characters in the password.

## 11. Deploy and inspect the environment

After applying the configuration:

1. Open the Elastic Beanstalk **Events** tab.
2. Wait for the environment health to become **Green**.
3. Open the environment URL.
4. Open:

```text
https://YOUR_ENV.elasticbeanstalk.com/health
```

Expected response:

```json
{"status":"ok"}
```

If deployment fails, inspect:

- **Events** for deployment errors.
- **Logs > Request Logs** for application output.
- **Logs > Full Logs** for Docker and Gunicorn errors.
- **Monitoring** for instance memory and CPU pressure.

## 12. Run database migrations

The RDS schema must be created before searches can work. Use an approved
maintenance access method to run commands in the same deployed environment.
Do not run migrations concurrently from every web instance.

Run:

```bash
python manage.py check --deploy
python manage.py migrate --noinput
```

If the AWS Console does not provide a shell for the selected platform version,
use one of these controlled approaches:

1. Temporarily connect through an approved Elastic Beanstalk SSH workflow.
2. Run a one-off maintenance task using the same Docker image and environment
   variables.
3. Run the command from a secure host inside the VPC with the application
   source and dependencies installed.

The key requirement is that the command uses the production `DATABASE_URL`.

## 13. Import the face embeddings into RDS

The local PKL file is deliberately excluded from the production image. Import
it once into RDS using a controlled machine that can reach the database:

```bash
python manage.py import_pkl_to_rds --glob "/secure/path/THF_face_database.pkl"
```

Verify the import with SQL:

```sql
SELECT COUNT(*) FROM search_faceembedding;
```

Do not configure the production application to use the local PKL database.
RDS is the production source of truth.

## 14. Configure HTTPS and a custom domain

For a public event deployment:

1. Open **AWS Certificate Manager**.
2. Request a public certificate for the event hostname.
3. Validate domain ownership.
4. Open the Elastic Beanstalk load balancer configuration.
5. Add an HTTPS listener on port `443`.
6. Attach the ACM certificate.
7. Configure HTTP-to-HTTPS redirect.
8. Update:
   - `DJANGO_ALLOWED_HOSTS` with the custom hostname.
   - `DJANGO_CSRF_TRUSTED_ORIGINS` with the full `https://` origin.
9. Apply the environment update.

After HTTPS is confirmed, set:

```text
DJANGO_SECURE_SSL_REDIRECT=true
DJANGO_HSTS_SECONDS=31536000
```

Do not enable long-lived HSTS before HTTPS is working correctly.

## 15. Final verification checklist

Before publishing the event QR code, confirm:

- [ ] Elastic Beanstalk health is Green.
- [ ] `/health` returns HTTP 200.
- [ ] The home page loads without a 500 response.
- [ ] A test selfie returns matches or the expected no-match state.
- [ ] Result images load from presigned S3 URLs.
- [ ] Direct unauthenticated S3 object URLs are denied.
- [ ] The RDS security group allows port `5432` only from Beanstalk.
- [ ] `LOCAL_PHOTO_DB_ENABLED=false` is set in AWS.
- [ ] S3 access is limited to `GetObject` and scoped `ListBucket`.
- [ ] No passwords or Django secrets appear in source, ZIP files, or logs.
- [ ] HTTPS works before enabling redirect and HSTS settings.
- [ ] CloudWatch/Beanstalk logs do not contain selfie data.

## Troubleshooting

### The application cannot connect to RDS

Check:

1. RDS and Elastic Beanstalk are in compatible VPC/subnet routing.
2. RDS inbound TCP `5432` allows the Beanstalk security group.
3. `DATABASE_URL` uses the RDS endpoint and database name `photomatch`.
4. The `vector` extension was created.
5. The database password is URL-encoded.

### Images show no preview

Check:

1. The S3 object exists under the configured `S3_IMAGE_PREFIX`.
2. `S3_BUCKET` contains only the bucket name, not `s3://`.
3. The EC2 instance profile has the read-only policy.
4. The bucket remains private but allows the application role to read.

### Elastic Beanstalk reports an unhealthy environment

Check:

1. The container listens on port `8080`.
2. Gunicorn starts `photomatch.wsgi:application`.
3. `/health` returns HTTP 200 inside the environment.
4. The Docker build completed successfully.
5. Instance memory is sufficient for `face_recognition` and OpenCV.

## References

- [Elastic Beanstalk Docker environments](https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/create_deploy_docker.html)
- [Elastic Beanstalk instance profiles](https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/iam-instanceprofile.html)
- [RDS PostgreSQL extensions](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Appendix.PostgreSQL.CommonDBATasks.Extensions.html)
- [S3 IAM actions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-with-s3-actions.html)
- [Django deployment checklist](https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/)
