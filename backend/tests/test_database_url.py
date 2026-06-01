from config import get_sqlalchemy_database_url


def test_supabase_session_pooler_uses_transaction_port():
    url = (
        "postgresql://postgres.ref:pw@"
        "aws-1-ap-northeast-2.pooler.supabase.com:5432/postgres"
    )

    assert (
        get_sqlalchemy_database_url(url)
        == "postgresql://postgres.ref:pw@aws-1-ap-northeast-2.pooler.supabase.com:6543/postgres"
    )


def test_non_supabase_database_url_is_unchanged():
    url = "postgresql://user:pw@example.com:5432/app"

    assert get_sqlalchemy_database_url(url) == url
