from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [("registry", "0014_unique_canonical_litter_birth")]
    operations = [
        migrations.AddField("dogtitle", "issuer", models.CharField(blank=True, max_length=160)),
        migrations.AddField("dogtitle", "awarded_on", models.DateField(blank=True, null=True)),
        migrations.AddField("dogtitle", "verification_state", models.CharField(
            max_length=20, default="community", choices=[
                ("community", "Community submitted"), ("source", "Source attached"),
                ("identity", "Identity reviewed"), ("pedigree", "Pedigree reviewed"),
                ("health", "Health/DNA verified"),
            ],
        )),
        migrations.AddField("dogtitle", "certificate_document", models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
            related_name="supported_titles", to="registry.dogdocument",
        )),
        migrations.AddField("disputecase", "target_image", models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
            related_name="photo_disputes", to="registry.dogimage",
        )),
        migrations.AlterField("disputecase", "reason", models.CharField(
            max_length=20, choices=[
                ("pedigree", "Pedigree relationship"), ("identity", "Dog identity"),
                ("health", "Health/DNA information"), ("ownership", "Kennel/ownership information"),
                ("duplicate", "Possible duplicate dog"), ("photo", "Incorrect dog photograph"),
                ("other", "Other"),
            ],
        )),
        migrations.AlterField("dogdocument", "document_type", models.CharField(
            max_length=20, default="other", choices=[
                ("pedigree", "Pedigree"), ("health", "Health"),
                ("registration", "External registration"), ("dna", "DNA"),
                ("title_certificate", "Club title certificate"), ("other", "Other"),
            ],
        )),
    ]
