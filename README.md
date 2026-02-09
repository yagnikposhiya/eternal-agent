# eternal-agent
A repository contains backend for an appointment booking voice AI agent. Frontend is available [here](https://github.com/yagnikposhiya/eternal-web)

## Teck stack
| Component | Tool | Free Tier |
|-----------|------|-----------|
| Voice Framework | LiveKit Agents (Python) | Cloud Free Tier |
| Speech → Text	| Deepgram | $200 credit |
| Text → Speech | Cartesia | 20k credit <br> (1 character = 1 credit) |
| Avatar | Beyond Presence | 140 minutes with just card verification |
| LLM | OpenAI/OpenRouter | Credit-based models are good |
| WebApp | Next.js | Build on top of the React.js |
| Database | Supabase | 2 projects are allowed |

## Required secrets
1. `LIVEKIT_URL`
2. `LIVEKIT_API_KEY`
3. `LIVEKIT_API_SECRET`
4. `DEEPGRAM_API_KEY`
5. `DEEPGRAM_MODEL`
6. `ANY_LLM_PLATFORM_API_KEY`
7. `CARTESIA_API_KEY`
8. `BEY_API_KEY`
9. `SUPABASE_URL`
10. `SUPABASE_SERVICE_ROLE_KEY`
11. `CARTESIA_VOICE_ID`
12. `BEY_AVATAR_ID`

## Backend setup as background worker in AWS EC2

### 1. Create AWS EC2 Instance
Minimum recommended specifications
1. 8 GB RAM
2. 2 vCPUs
3. 30 GB EBS storage
4. Ubuntu 24.04 LTS

### 2. Connect to the Instance
Either via SSH or AWS Console.

### 3. Set up Python Environment
1. Update system packages: `sudo apt update`
2. Install Python venv: `sudo apt install python3.12-venv`
3. Create a directory for Python environments:`mkdir python-envs`
4. Create the virtual environment: `python3 -m venv python-envs/env-eternal-agent`
5. Clone the repository: `git clone https://github.com/yagnikposhiya/eternal-agent.git`
6. Activate the virtual environment: `source /home/ubuntu/python-envs/env-eternal-agent/bin/activate`
7. Create `.env` file to store secrets: `nano .env`
8. Move to project directory: `cd eternal-agent`
9. Download required models: `python3 -m venv src.main download-files`
10. If the above command fails on EC2, manually download files locally -> create zip -> upload to EC2 -> extract into: `/home/ubuntu/.cache/huggingface/hub`

### 4. Create a systemd Service (Auto-start on Crash/Boot)
1. Create the service file: `sudo nano /etc/systemd/system/eternal-agent.service`
2. Set the configuration:
```
[Unit]
Description=Eternal Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/eternal-agent

ExecStart=/home/ubuntu/python-envs/env-eternal-agent/bin/python -m src.main start

Restart=always
RestartSec=3

Environment=PYTHONUNBUFFERED=1
# Environment=HF_HOME=/home/ubuntu/.cache/huggingface

StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

5. Reload systemd: `sudo systemctl daemon-reload`
6. Enable and start the agent service: `sudo systemctl enable --now eternal-agent`
7. Check service status: `sudo systemctl status eternal-agent --no-pager`
8. View live logs: `sudo journalctl -u eternal-agent -f`

## Supabase database setup (Auto schema from migrations)
> These steps are only valid for Linux/macOS terminals (bash/zsh). On Windows, use WSL2 or adapt the commands to PowerShell.

### 1. New to Supabase CLI (Fresh setup)
1. Download the Supabase CLI Debian package from [@supabase/cli](https://github.com/supabase/cli/releases)
2. Install Supabase CLI using `sudo dpkg -i <package-name>.deb`
3. Log in to Supabase CLI: `supabase login`
4. Create a Supabase project in the browser (no CLI command – do this in the Supabase dashboard)
5. Link this repository to your Supabase project: `supabase link --project-ref <YOUR_PROJECT_REF/YOUR_PROJECT_URL>`
6. Apply the schema (migrations) to your project: `supabase db push`. This creates all tables, functions, and RLS policies in your Supabase project from `supabase/migrations/*.sql`.
7. Configure backend environment variables: `cp .env.example .env`. Then edit `.env` and set `SUPABASE_URL` from your Supabase project settings.

### 2. Already using Supabase CLI (Apply schema to an existing Supabase cloud project)
1. Link this repo to your existing Supabase project (only needed once per repo/project): `supabase link --project-ref <YOUR_PROJECT_REF>`
2. Apply the same schema from this repo to your cloud project’s database: `supabase db push`
3. Configure backend environment variables: `cp .env.example .env`. Then edit `.env` and set `SUPABASE_URL` from your Supabase project settings.
