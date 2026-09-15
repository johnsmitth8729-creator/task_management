# Multi-Channel Communication & External Integrations Architecture (Phase 12)

## 1. Overview
The Communication & Integration module acts as the centralized multi-channel notification dispatcher and external data bridge for the University Task Management Platform.

## 2. Notification Dispatcher Architecture
The unified `NotificationDispatcher` dispatches event notifications across 4 independent delivery channels based on granular user preferences:
- **In-App Notification**: Persistent DB record (`core.Notification`) rendered in real-time navigation drop-downs.
- **Email Notifications**: Multipart HTML/plain text transactional emails via Django SMTP backend.
- **Telegram Bot Integration**: Real-time push messaging to verified Telegram chat IDs via the Telegram Bot API (`TelegramService`).
- **Web Push (W3C Standard)**: VAPID-signed Web Push notifications directly into staff desktop/mobile browsers.

```
                  ┌────────────────────────────────────────┐
                  │          Event Trigger                 │
                  │   (Assignment / Status / SLA / Req)    │
                  └──────────────────┬─────────────────────┘
                                     │
                                     ▼
                  ┌────────────────────────────────────────┐
                  │         NotificationDispatcher         │
                  │   - Category & Channel Filtering       │
                  │   - User Preferences Enforcement       │
                  └──────┬──────────┬──────────┬───────────┘
                         │          │          │           │
           ┌─────────────┘          │          │           └──────────────┐
           ▼                        ▼          ▼                          ▼
     ┌───────────┐            ┌───────────┐  ┌───────────┐          ┌───────────┐
     │  In-App   │            │   Email   │  │ Telegram  │          │ Web Push  │
     │  Storage  │            │   SMTP    │  │  Bot API  │          │   VAPID   │
     └───────────┘            └───────────┘  └───────────┘          └───────────┘
```

## 3. RFC 5545 iCalendar Feeds
Staff can subscribe their Google Calendar, Apple Calendar, or Microsoft Outlook clients to their university tasks and deadlines:
- Secure, tokenized feed endpoints (`/communication/calendar/feed/<uuid:feed_token>/tasks.ics`).
- Real-time VEVENT generation with VTODO, alarms (VALARM), task priority, and deep URLs.

## 4. Academic & Financial Connectors
- **HEMIS Integration**: Synchronizes academic faculties, departments, courses, and student/faculty associations from the National Higher Education Management Information System.
- **Moodle LMS**: Bridges LMS task assignments and curriculum deadlines.
- **UzASBO / 1C Accounting**: Synchronizes payroll accounting ledgers and university fiscal compensation records.
- **Audit Sync Logs**: `IntegrationSyncLog` records every sync execution, payload volume, latency, and status.
