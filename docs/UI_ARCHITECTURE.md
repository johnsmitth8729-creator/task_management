# UI Architecture

## Stack

Use:

- HTML5
- CSS3
- JavaScript
- Bootstrap 5
- Bootstrap Icons
- Chart.js where charts are required

Avoid unnecessary frontend frameworks.

## Layout

Reusable UI structure:

- base layout
- navbar
- sidebar
- breadcrumbs
- responsive content container
- language switcher
- user menu
- notification menu

## Components

Reusable components:

- dashboard cards
- task cards
- task detail sections
- status badges
- priority badges
- modal dialogs
- forms
- tables
- filters
- pagination
- notifications
- timeline
- charts
- empty states
- loading states
- error states

## Templates

Use Django template inheritance:

- `base.html`
- app-specific layouts where needed
- reusable includes/components

All UI text must use translation tags.

## Responsive Design

The UI must work on desktop and mobile:

- collapsible sidebar
- readable tables or responsive table alternatives
- touch-friendly buttons
- stacked form layout on narrow screens
- no overlapping text or controls

## Accessibility

Use:

- semantic HTML
- proper labels for forms
- accessible button text or aria labels for icon buttons
- sufficient color contrast
- keyboard-accessible navigation

## Chart Data

Chart.js should receive data from authorized backend endpoints or embedded server-rendered JSON. Chart data must respect the same role and department scope permissions.

## Frontend Security

Frontend controls may hide unavailable actions for usability, but backend authorization remains mandatory.

