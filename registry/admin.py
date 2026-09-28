from django.contrib import admin

from .models import (
    Dog,
    DogAlias,
    DogImage,
    DogRegistration,
    DogSource,
    HealthRecord,
    Kennel,
    KennelMembership,
    Litter,
    RegistrationAuthority,
)


class DogRegistrationInline(admin.TabularInline):
    model = DogRegistration
    extra = 0


class DogAliasInline(admin.TabularInline):
    model = DogAlias
    extra = 0


@admin.register(Dog)
class DogAdmin(admin.ModelAdmin):
    list_display = ("name", "sex", "kennel", "verification_state", "is_public")
    list_filter = ("sex", "verification_state", "is_public", "country")
    search_fields = ("name", "aliases__name", "registrations__number")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("sire", "dam", "kennel", "litter")
    inlines = (DogAliasInline, DogRegistrationInline)


@admin.register(Kennel)
class KennelAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "city", "verified_at")
    search_fields = ("name", "country", "city")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Litter)
class LitterAdmin(admin.ModelAdmin):
    list_display = ("code", "kennel", "date_of_birth", "is_public")
    search_fields = ("code",)


admin.site.register(KennelMembership)
admin.site.register(RegistrationAuthority)
admin.site.register(DogImage)
admin.site.register(HealthRecord)
admin.site.register(DogSource)
