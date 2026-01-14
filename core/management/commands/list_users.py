from django.core.management.base import BaseCommand
from django.db.models import Count
from core.models import User


class Command(BaseCommand):
    help = 'List all users with their roles and types'

    def add_arguments(self, parser):
        parser.add_argument(
            '--role',
            type=str,
            help='Filter users by role (student, teacher, staff, other)',
        )

    def handle(self, *args, **options):
        role_filter = options.get('role')
        
        # Query users
        if role_filter:
            users = User.objects.filter(role=role_filter)
            self.stdout.write(self.style.WARNING(f'\nFiltering by role: {role_filter}\n'))
        else:
            users = User.objects.all()
        
        if not users.exists():
            self.stdout.write(self.style.WARNING('No users found.'))
            return
        
        # Print header
        self.stdout.write('=' * 90)
        self.stdout.write(
            f'{"ID":<5} {"Username":<20} {"Email":<30} {"Role":<15} {"Staff":<8} {"Active":<8} {"Superuser":<10}'
        )
        self.stdout.write('=' * 90)
        
        # Print each user
        for user in users:
            self.stdout.write(
                f'{user.id:<5} '
                f'{user.username:<20} '
                f'{(user.email or "N/A"):<30} '
                f'{user.get_role_display():<15} '
                f'{"Yes" if user.is_staff else "No":<8} '
                f'{"Yes" if user.is_active else "No":<8} '
                f'{"Yes" if user.is_superuser else "No":<10}'
            )
        
        self.stdout.write('=' * 90)
        
        # Print summary
        total = users.count()
        self.stdout.write(f'\nTotal users: {total}')
        
        if not role_filter:
            # Show user types summary
            self.stdout.write('\nUser Types Summary:')
            role_counts = User.objects.values('role').annotate(
                count=Count('id')
            ).order_by('role')
            
            for role_data in role_counts:
                role = role_data['role']
                count = role_data['count']
                role_display = dict(User.ROLE_CHOICES).get(role, role.title())
                self.stdout.write(f'  {role_display:<15} : {count}')

