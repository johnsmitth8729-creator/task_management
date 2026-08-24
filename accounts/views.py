from django.contrib.auth.views import LoginView, LogoutView

from .forms import LoginForm


class UserLoginView(LoginView):
    authentication_form = LoginForm
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True

    def form_valid(self, form):
        remember_me = form.cleaned_data.get('remember_me')
        if not remember_me:
            self.request.session.set_expiry(0)
        else:
            self.request.session.set_expiry(None)
        return super().form_valid(form)


class UserLogoutView(LogoutView):
    http_method_names = ['post', 'options']
