from app import ratelimit


def test_idle_clients_are_forgotten_so_memory_does_not_grow():
    ratelimit.reset()
    ratelimit._hits["login:1.2.3.4"].append(0.0)  # an old hit from a client that went away
    ratelimit._hits["login:5.6.7.8"].append(1000.0)  # a recent client
    ratelimit._sweep(now=1000.0, window_s=60)
    assert "login:1.2.3.4" not in ratelimit._hits
    assert "login:5.6.7.8" in ratelimit._hits
    ratelimit.reset()


def test_sweep_runs_at_most_once_a_minute():
    ratelimit.reset()
    ratelimit._sweep(now=500.0, window_s=60)
    ratelimit._hits["a:b"].append(0.0)
    ratelimit._sweep(now=510.0, window_s=60)  # too soon: nothing removed
    assert "a:b" in ratelimit._hits
    ratelimit.reset()
