from django.db import models


class Game(models.Model):
    """Une partie dont on suit la consommation de jetons."""

    game_id = models.CharField(max_length=64, unique=True)
    started_at = models.DateTimeField()

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return self.game_id


class RoundCost(models.Model):
    """Jetons consommés pendant une manche (un cycle nuit + jour) d'une partie."""

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="rounds")
    round = models.PositiveIntegerField()
    calls = models.PositiveIntegerField(default=0)
    prompt_tokens = models.PositiveBigIntegerField(default=0)
    completion_tokens = models.PositiveBigIntegerField(default=0)
    total_tokens = models.PositiveBigIntegerField(default=0)

    class Meta:
        ordering = ["game", "round"]
        constraints = [models.UniqueConstraint(fields=["game", "round"], name="unique_round_per_game")]

    def __str__(self) -> str:
        return f"{self.game} — manche {self.round} : {self.total_tokens} jetons"
