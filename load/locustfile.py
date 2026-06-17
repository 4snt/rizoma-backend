"""Testes de carga e estresse da API Rizoma (Locust).

Uso:
    pip install locust
    # Carga normal (UI web em http://localhost:8089):
    locust -f load/locustfile.py --host http://localhost:8000
    # Headless, 100 usuários, ramp de 10/s, por 2 min:
    locust -f load/locustfile.py --host http://localhost:8000 \
           --headless -u 100 -r 10 -t 2m

Cenários:
  ReadOnlyUser  → carga de leitura realista (endpoints públicos GET).
  StressUser    → estresse: praticamente sem pausa entre requisições.
"""
from locust import HttpUser, task, between, constant


class ReadOnlyUser(HttpUser):
    """Usuário típico navegando: leitura de projetos, status do worker, health."""
    wait_time = between(1, 4)

    @task(3)
    def list_projects(self):
        self.client.get("/api/v1/projects/", name="GET /projects")

    @task(2)
    def worker_status(self):
        self.client.get("/api/v1/worker/status", name="GET /worker/status")

    @task(1)
    def health(self):
        self.client.get("/health", name="GET /health")


class StressUser(HttpUser):
    """Estresse: martela os endpoints de leitura sem pausa para achar o limite.

    Rode isolando esta classe:
        locust -f load/locustfile.py StressUser --host http://localhost:8000 \
               --headless -u 500 -r 50 -t 3m
    """
    wait_time = constant(0)

    @task
    def hammer_projects(self):
        self.client.get("/api/v1/projects/", name="STRESS GET /projects")

    @task
    def hammer_status(self):
        self.client.get("/api/v1/worker/status", name="STRESS GET /worker/status")
