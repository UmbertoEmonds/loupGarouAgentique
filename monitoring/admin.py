"""Admin Django en lecture seule : les coûts sont écrits par le jeu, pas à la main."""

from django.contrib import admin
from django.db.models import Count, Sum

from monitoring.models import Game, RoundCost

admin.site.site_header = "Loups-Garous — suivi des coûts"
admin.site.site_title = "Suivi des coûts"
admin.site.index_title = "Coût en jetons par partie et par manche"


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class RoundCostInline(admin.TabularInline):
    model = RoundCost
    fields = ("round", "calls", "prompt_tokens", "completion_tokens", "total_tokens")
    readonly_fields = fields
    extra = 0
    can_delete = False
    ordering = ("round",)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Game)
class GameAdmin(ReadOnlyAdmin):
    list_display = ("game_id", "started_at", "round_count", "call_count",
                    "prompt_tokens", "completion_tokens", "total_tokens")
    date_hierarchy = "started_at"
    search_fields = ("game_id",)
    inlines = [RoundCostInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _rounds=Count("rounds"),
            _calls=Sum("rounds__calls"),
            _prompt=Sum("rounds__prompt_tokens"),
            _completion=Sum("rounds__completion_tokens"),
            _total=Sum("rounds__total_tokens"),
        )

    @admin.display(description="Manches", ordering="_rounds")
    def round_count(self, obj):
        return obj._rounds

    @admin.display(description="Appels LLM", ordering="_calls")
    def call_count(self, obj):
        return obj._calls or 0

    @admin.display(description="Jetons prompt", ordering="_prompt")
    def prompt_tokens(self, obj):
        return obj._prompt or 0

    @admin.display(description="Jetons réponse", ordering="_completion")
    def completion_tokens(self, obj):
        return obj._completion or 0

    @admin.display(description="Jetons total", ordering="_total")
    def total_tokens(self, obj):
        return obj._total or 0


@admin.register(RoundCost)
class RoundCostAdmin(ReadOnlyAdmin):
    list_display = ("game", "round", "calls", "prompt_tokens", "completion_tokens", "total_tokens")
    list_filter = ("round",)
    search_fields = ("game__game_id",)
    list_select_related = ("game",)
    ordering = ("-game__started_at", "round")
