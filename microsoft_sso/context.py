from microsoft_sso import conf


def sso_context(request):
    return {"sso_enabled": conf.enabled(), "sso_dev_mock": conf.mock_enabled()}
