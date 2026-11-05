from django.db import models


class Game(models.Model):
    """Une partie dont on suit la consommation de jetons."""

    game_id = models.CharField("identifiant de partie", max_length=64, unique=True)
    started_at = models.DateTimeField("début de partie")

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "partie"
        verbose_name_plural = "parties"

    def __str__(self) -> str:
        return self.game_id


class RoundCost(models.Model):
    """Jetons consommés pendant une manche (un cycle nuit + jour) d'une partie."""

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="rounds", verbose_name="partie")
    round = models.PositiveIntegerField("manche")
    calls = models.PositiveIntegerField("appels LLM", default=0)
    prompt_tokens = models.PositiveBigIntegerField("jetons prompt", default=0)
    completion_tokens = models.PositiveBigIntegerField("jetons réponse", default=0)
    total_tokens = models.PositiveBigIntegerField("jetons total", default=0)

    class Meta:
        ordering = ["game", "round"]
        verbose_name = "coût d'une manche"
        verbose_name_plural = "coûts par manche"
        constraints = [models.UniqueConstraint(fields=["game", "round"], name="unique_round_per_game")]

    def __str__(self) -> str:
        return f"{self.game} — manche {self.round} : {self.total_tokens} jetons"
