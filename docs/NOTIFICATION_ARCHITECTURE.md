# Notification Architecture

## Phase Boundary

Phase 0 defines the architecture only. Full notification implementation is reserved for later phases.

## Goals

Notifications must support:

- database storage
- read/unread state
- timestamps
- notification type
- target user
- related object
- future real-time delivery

## Notification Events

Planned notification types:

- new task
- task assignment
- task acceptance
- task submission
- first approval
- rejection
- second approval pending
- final approval
- deadline warning
- overdue
- deadline change
- escalation

## Model

`Notification` fields:

- target user
- notification type
- title translation key
- message translation key
- context JSON
- related content type
- related object id
- read_at
- created_at

## Dispatch Flow

1. Domain service performs business operation.
2. Domain service records history and audit.
3. Domain service calls notification service with event code and recipients.
4. Notification service writes database notification rows.
5. Celery can later deliver email, WebSocket, or external notifications.

## Internationalization

Store translation keys and context data, not final rendered message text. Render notifications in the user's selected language at display time.

## Real-Time Support

Initial architecture uses database notifications. Later Django Channels can subscribe users to notification streams and broadcast newly created notification events.

## Permission Rule

A notification does not grant access. When a user clicks a notification, the target object must still be fetched through the normal authorized queryset and object-level permission policy.

