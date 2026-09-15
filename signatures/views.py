import json
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views import View
from django.views.decorators.http import require_GET, require_POST

from signatures.models import ElectronicSignature
from signatures.permissions import can_revoke_signature, can_sign_task
from signatures.qr import generate_qr_data_uri, generate_qr_image
from signatures.services import revoke_signature, sign_task, verify_signature
from tasks.models import Task


class SignTaskView(View):
    """
    Handles authenticated POST request from authorized Rector / Vice Rector / Superadmin
    to electronically sign a completed task.
    """

    @method_decorator(login_required)
    def post(self, request, task_id):
        task = get_object_or_404(Task, pk=task_id)

        # Check permission before proceeding
        is_allowed, reason = can_sign_task(request.user, task)
        if not is_allowed:
            messages.error(request, reason)
            return redirect('task_detail', pk=task.pk)

        # Validate confirmation checkbox from modal
        confirmed = request.POST.get('confirm_signature')
        if not confirmed:
            messages.error(request, _('You must check the confirmation checkbox to electronically sign this task.'))
            return redirect('task_detail', pk=task.pk)

        try:
            signature = sign_task(task=task, signer=request.user, request=request)
            messages.success(
                request,
                _('Task {task_num} has been successfully electronically signed! Verification ID: {ver_id}').format(
                    task_num=task.task_number,
                    ver_id=signature.verification_id,
                ),
            )
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))
        except Exception as e:
            messages.error(request, _('An unexpected error occurred during electronic signing.'))

        return redirect('task_detail', pk=task.pk)


@require_GET
def public_verification_view(request, verification_id):
    """
    Public electronic signature verification page.
    No login required. GET only.
    Exposes only safe, official public task verification attributes.
    """
    result = verify_signature(verification_id, request=request)
    verification_url = request.build_absolute_uri(
        reverse('public_verify', kwargs={'verification_id': verification_id})
    )
    qr_data_uri = generate_qr_data_uri(verification_url)

    context = {
        'verification': result,
        'verification_id': verification_id,
        'verification_url': verification_url,
        'qr_data_uri': qr_data_uri,
        'is_public': True,
    }
    return render(request, 'signatures/verify.html', context)


@require_GET
def signature_qr_view(request, verification_id):
    """
    Streams dynamic server-generated PNG QR code encoding the public verification URL.
    Supports ?download=1 to prompt file save dialog.
    """
    signature = ElectronicSignature.objects.filter(verification_id=verification_id).first()
    if not signature:
        raise Http404(_('Signature not found.'))

    verification_url = f"http://127.0.0.1:8000/verify/{signature.verification_id}/"
    if request:
        try:
            verification_url = request.build_absolute_uri(
                reverse('public_verify', kwargs={'verification_id': signature.verification_id})
            )
        except Exception:
            pass

    buffer = generate_qr_image(verification_url, box_size=8, border=2)

    response = HttpResponse(buffer.getvalue(), content_type='image/png')
    if request.GET.get('download') == '1':
        response['Content-Disposition'] = f'attachment; filename="QR_{signature.verification_id}.png"'
    return response


@require_GET
def download_signed_pdf_view(request, verification_id):
    """
    Downloads or displays the official electronically signed PDF document
    with proportional university logo, complete task information, execution processes, and QR code.
    """
    signature = ElectronicSignature.objects.filter(verification_id=verification_id).select_related('task', 'signer').first()
    if not signature:
        raise Http404(_('Signature not found.'))

    from django.core.files.base import ContentFile
    from signatures.pdf import generate_signed_task_pdf

    # Generate fresh proportional PDF to ensure latest design & aspect ratio
    pdf_buffer = generate_signed_task_pdf(signature, request=request)
    pdf_bytes = pdf_buffer.getvalue()
    pdf_filename = f"Topshiriq_{signature.task.task_number}_Elektron_Imzo_{signature.verification_id}.pdf"
    try:
        signature.signed_pdf.save(pdf_filename, ContentFile(pdf_bytes), save=True)
    except Exception:
        pass

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    disposition = 'attachment' if request.GET.get('download') == '1' else 'inline'
    response['Content-Disposition'] = f'{disposition}; filename="{pdf_filename}"'
    return response


class RevokeSignatureView(View):
    """
    Revokes an active electronic signature. Authorized for Superadmin and Rector only.
    """

    @method_decorator(login_required)
    def post(self, request, signature_id):
        signature = get_object_or_404(ElectronicSignature, pk=signature_id)
        if not can_revoke_signature(request.user, signature):
            raise PermissionDenied(_('You do not have authority to revoke this signature.'))

        reason = request.POST.get('revocation_reason', '').strip()
        if not reason:
            messages.error(request, _('A revocation reason is required.'))
            return redirect('task_detail', pk=signature.task_id)

        try:
            revoke_signature(signature=signature, actor=request.user, reason=reason, request=request)
            messages.warning(
                request,
                _('Electronic signature {ver_id} has been revoked.').format(ver_id=signature.verification_id),
            )
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, 'message') else e))

        return redirect('task_detail', pk=signature.task_id)


# ===========================================================================
# JSON API ENDPOINTS
# ===========================================================================

@login_required
@require_POST
def api_sign_task(request, task_id):
    """API endpoint to electronically sign a task."""
    task = get_object_or_404(Task, pk=task_id)
    is_allowed, reason = can_sign_task(request.user, task)
    if not is_allowed:
        return JsonResponse({'success': False, 'error': reason}, status=403)

    try:
        sig = sign_task(task=task, signer=request.user, request=request)
        verification_url = request.build_absolute_uri(
            reverse('public_verify', kwargs={'verification_id': sig.verification_id})
        )
        return JsonResponse({
            'success': True,
            'verification_id': sig.verification_id,
            'verification_url': verification_url,
            'signed_at': sig.signed_at.isoformat(),
            'signer': sig.signer.display_name,
            'status': sig.status,
        })
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e.message if hasattr(e, 'message') else e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(_('Signing error'))}, status=500)


@require_GET
def api_verify_signature(request, verification_id):
    """Public API endpoint returning safe JSON verification details."""
    result = verify_signature(verification_id, request=request)
    if result.get('status') == 'NOT_FOUND':
        return JsonResponse(result, status=404)
    return JsonResponse(result, status=200)
