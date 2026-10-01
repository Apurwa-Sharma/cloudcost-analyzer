# AI Cloud Cost Detective — Architecture

## System Architecture

```text
                              ┌──────────────┐
                              │     USER     │
                              └──────┬───────┘
                                     │
                                     ▼
                           ┌───────────────────┐
                           │  REACT FRONTEND   │
                           │ Vite + TypeScript │
                           │     + Tailwind    │
                           └────────┬──────────┘
                                    │
                                    │ Login / Signup
                                    ▼
                           ┌───────────────────┐
                           │  PYTHON BACKEND   │
                           │     FastAPI       │
                           │                   │
                           │   Custom JWT Auth │
                           └───┬───────┬───┬───┘
                               │       │   │
                ┌──────────────┘       │   └──────────────┐
                │                      │                  │
                ▼                      ▼                  ▼
         ┌─────────────┐     ┌──────────────┐    ┌──────────────┐
         │ AWS CLI +   │     │   FASTAPI    │    │   GEMINI     │
         │   BOTO3     │     │  WEBSOCKET   │    │     API      │
         │             │     │              │    │              │
         │ AWS Resource│     │ Live Progress│    │ AI Cost      │
         │ Discovery   │     │ & Updates    │    │ Analysis     │
         └──────┬──────┘     └──────┬───────┘    └──────┬───────┘
                │                   │                   │
                │                   │ Live Updates      │
                ▼                   ▼                   │
         ┌─────────────┐   ┌───────────────┐            │
         │     AWS     │   │    REACT      │            │
         │  Resources  │   │   Progress    │            │
         │             │   │    Tracker    │            │
         │ EC2 / S3 /  │   └───────────────┘            │
         │ EBS / RDS / │                                │
         │ CloudWatch  │                                │
         └─────────────┘                                │
                                                        │
                                                        ▼
                                                 ┌──────────────┐
                                                 │  POSTGRESQL  │
                                                 │              │
                                                 │    users     │
                                                 │   analyses   │
                                                 └──────┬───────┘
                                                        │
                                                        │ Stored Results
                                                        ▼
                                                 ┌───────────────┐
                                                 │    REACT      │
                                                 │               │
                                                 │ Final Report  │
                                                 │ Suggestions   │
                                                 │    + Fixes    │
                                                 └───────────────┘
