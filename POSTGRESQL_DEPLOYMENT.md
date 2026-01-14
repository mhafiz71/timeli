# PostgreSQL Deployment Guide for Timeli Timetable System

## Overview
This guide explains how to deploy the Django timetable system to Render with an external PostgreSQL database for persistent data storage, solving the data synchronization issue between development and production.

**Note**: Render no longer offers free PostgreSQL databases. This guide uses external PostgreSQL hosting services that offer free tiers.

## What This Solves
- **Data Persistence**: PostgreSQL database persists across deployments
- **No Data Loss**: Your timetables and user data won't be lost on redeploy
- **Synchronized Data**: Development fixtures are automatically loaded to production
- **Consistent Environment**: Same data structure in both development and production

## Prerequisites
- Render account (for hosting the web service)
- External PostgreSQL database account (choose one from options below)
- Git repository with your code
- Current development data exported as fixtures (✓ Already done)

## Step 1: Set Up External PostgreSQL Database

Since Render no longer offers free PostgreSQL databases, you'll need to use an external PostgreSQL hosting service. Here are recommended options:

### Option A: Neon (Serverless PostgreSQL - Recommended)

**Why Neon?**
- ✅ Generous free tier (0.5GB storage, 10GB transfer)
- ✅ Serverless architecture - scales automatically
- ✅ Built-in connection pooling
- ✅ Branching (database branching like Git)
- ✅ Automatic backups
- ✅ No credit card required for free tier

**Setup Steps:**

1. **Create Neon Account:**
   - Go to [neon.tech](https://neon.tech)
   - Sign up for a free account
   - Create a new project

2. **Get Database Connection String:**
   - In your Neon project dashboard, go to **Connection Details**
   - Copy the connection string (pooler or direct connection)
   - **For Django, use the pooler connection** (recommended for serverless)
   - Format: `postgresql://user:password@host/database?sslmode=require`

3. **Your Neon Connection String:**
   ```
   postgresql://neondb_owner:npg_Pm6pbMRzU5gA@ep-divine-tree-ahu5dja4-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require
   ```
   - This is ready to use in Render's DATABASE_URL environment variable

### Option B: Supabase (Alternative - Easiest Setup)

**Why Supabase?**
- ✅ Generous free tier (500MB database, unlimited API requests)
- ✅ Easy-to-use dashboard
- ✅ Built-in connection pooling
- ✅ Automatic backups
- ✅ No credit card required for free tier

**Setup Steps:**

1. **Create Supabase Account:**
   - Go to [supabase.com](https://supabase.com)
   - Sign up for a free account
   - Create a new project

2. **Get Database Connection String:**
   - In your Supabase project dashboard, go to **Settings** → **Database**
   - Scroll down to **Connection string** section
   - Select **URI** tab
   - Copy the connection string (it will look like: `postgresql://postgres:[YOUR-PASSWORD]@db.xxxxx.supabase.co:5432/postgres`)
   - **Important**: Replace `[YOUR-PASSWORD]` with your actual database password (found in project settings)

3. **Save the Connection String:**
   - You'll need this for Step 2
   - Format: `postgresql://postgres:password@host:port/postgres`

### Option C: ElephantSQL (Alternative)

**Why ElephantSQL?**
- ✅ Free tier available (20MB database)
- ✅ Simple setup
- ✅ PostgreSQL 15+ support

**Setup Steps:**

1. **Create ElephantSQL Account:**
   - Go to [elephantsql.com](https://www.elephantsql.com)
   - Sign up for free account
   - Click "Create New Instance"

2. **Configure Instance:**
   - Plan: Select "Tiny Turtle" (Free)
   - Name: `timeli-db`
   - Region: Choose closest to your Render region
   - Click "Select Region"

3. **Get Database URL:**
   - Once created, click on your instance
   - Copy the "URL" field
   - Format: `postgresql://user:password@host:port/database`

### Option D: Railway (Alternative)

**Why Railway?**
- ✅ $5 free credit monthly
- ✅ Easy PostgreSQL setup
- ✅ Good performance

**Setup Steps:**

1. **Create Railway Account:**
   - Go to [railway.app](https://railway.app)
   - Sign up with GitHub
   - Click "New Project"

2. **Add PostgreSQL:**
   - Click "New" → "Database" → "Add PostgreSQL"
   - Railway automatically creates the database

3. **Get Database URL:**
   - Click on the PostgreSQL service
   - Go to "Variables" tab
   - Copy the `DATABASE_URL` value

### Option E: Aiven (Alternative)

**Why Aiven?**
- ✅ Free tier with $300 credit
- ✅ PostgreSQL 14+ support
- ✅ Good for production use

**Setup Steps:**

1. **Create Aiven Account:**
   - Go to [aiven.io](https://aiven.io)
   - Sign up for free account
   - Create a new PostgreSQL service

2. **Get Connection String:**
   - In service overview, find "Connection information"
   - Copy the PostgreSQL connection URI

---

## 🚀 Quick Start: Neon Integration (Already Configured)

**If you're using Neon (already set up):**

Your Neon connection string is ready:
```
postgresql://neondb_owner:npg_Pm6pbMRzU5gA@ep-divine-tree-ahu5dja4-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require
```

**Next Steps:**
1. ✅ Neon database is already set up
2. ⏭️ Skip to **Step 3** to deploy on Render
3. 🔑 Set `DATABASE_URL` environment variable in Render dashboard with the connection string above

---

## Step 2: Update render.yaml Configuration

Since we're using an external database, we need to update `render.yaml` to remove the database service and manually set the `DATABASE_URL`:

1. **Update render.yaml:**
   - Remove the `pserv` (PostgreSQL service) section
   - The file should only contain the web service configuration
   - You'll manually set `DATABASE_URL` as an environment variable

2. **Updated render.yaml should look like:**
   ```yaml
   services:
     - type: web
       name: timeli-web
       env: python
       runtime: python-3.11.9
       buildCommand: pip install --upgrade pip && pip install -r requirements.txt && python manage.py migrate && python manage.py seed_data && python manage.py collectstatic --noinput
       startCommand: gunicorn timeli.wsgi:application
       envVars:
         - key: DATABASE_URL
           value: YOUR_DATABASE_URL_HERE  # You'll set this in Render dashboard
         - key: DJANGO_SETTINGS_MODULE
           value: timeli.settings
         - key: DEBUG
           value: False
         - key: SECRET_KEY
           generateValue: true
   ```

   **Note**: For security, don't put your actual database URL in the YAML file. Instead, set it as an environment variable in Render dashboard (see Step 3).

## Step 3: Deploy Web Service on Render

### Option A: Using render.yaml (Recommended)
1. **Update render.yaml** (remove database service section as shown above)
2. Commit changes to your repository:
   ```bash
   git add render.yaml
   git commit -m "Update render.yaml for external PostgreSQL"
   git push
   ```

3. In Render Dashboard:
   - Click "New" → "Blueprint"
   - Connect your GitHub repository
   - Select the repository with `render.yaml`
   - **Before clicking "Apply"**, you'll need to manually set the DATABASE_URL (see below)

### Option B: Manual Setup
1. **Create Web Service:**
   - Click "New" → "Web Service"
   - Connect your GitHub repository
   - Configure:
     - Name: `timeli-web`
     - Environment: Python 3
     - Build Command: 
       ```bash
       pip install --upgrade pip && pip install -r requirements.txt && python manage.py migrate && python manage.py seed_data && python manage.py collectstatic --noinput
       ```
     - Start Command: `gunicorn timeli.wsgi:application`

2. **Set Environment Variables in Render Dashboard:**
   - Go to your web service → "Environment" tab
   - Add the following environment variables:
     - `DATABASE_URL`: Paste the PostgreSQL connection string from Step 1
       - **For Neon**: `postgresql://neondb_owner:npg_Pm6pbMRzU5gA@ep-divine-tree-ahu5dja4-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require`
       - **For Supabase**: `postgresql://postgres:password@db.xxxxx.supabase.co:5432/postgres`
     - `DJANGO_SETTINGS_MODULE`: `timeli.settings`
     - `DEBUG`: `False`
     - `SECRET_KEY`: Click "Generate" or use a secure random string

   **Important**: 
   - Never commit your `DATABASE_URL` to git
   - Always set it as an environment variable in Render dashboard
   - The connection string should include your actual password
   - **For Neon**: Use the pooler connection (already included in your string)

## Step 4: Verify Deployment

1. **Check Build Logs:**
   - Ensure migrations run successfully
   - Verify fixtures are loaded with `seed_data` command
   - Look for "✓ Database seeded successfully!" message

2. **Test Application:**
   - Visit your Render app URL
   - Test login with existing users from development
   - Verify admin panel works with existing admin accounts
   - Check that master timetables are present

## Step 5: Future Data Management

### Adding New Data
When you add new timetables or make changes:

1. **In Development:**
   ```bash
   # Make your changes (add timetables, users, etc.)
   
   # Export updated data
   python manage.py dumpdata core.TimetableSource --indent 2 --output fixtures/timetables.json
   python manage.py dumpdata core.User --indent 2 --output fixtures/users.json
   python manage.py dumpdata core.CourseRegistrationHistory --indent 2 --output fixtures/course_history.json
   ```

2. **Deploy to Production:**
   ```bash
   git add fixtures/
   git commit -m "Update production data fixtures"
   git push
   ```

3. **Render automatically:**
   - Redeploys your app
   - Runs migrations
   - Loads updated fixtures
   - Preserves existing data in PostgreSQL

### Database Persistence Benefits
- ✅ PostgreSQL database persists across deployments
- ✅ Data is NOT lost when you redeploy your application
- ✅ Only new migrations and fixture updates are applied
- ✅ User accounts and course history remain intact
- ✅ Master timetables are preserved and updated

## Files Created for This Solution

### 1. Updated requirements.txt
```
psycopg2-binary==2.9.7  # PostgreSQL adapter
dj-database-url==2.1.0  # Database URL parsing
```

### 2. Updated timeli/settings.py
```python
# Automatic database switching
if os.environ.get('DATABASE_URL'):
    # Production: PostgreSQL
    DATABASES = {
        'default': dj_database_url.parse(os.environ.get('DATABASE_URL'))
    }
else:
    # Development: SQLite
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
```

### 3. Data Fixtures (✓ Already created)
- `fixtures/users.json` - Your user accounts
- `fixtures/timetables.json` - Master timetables
- `fixtures/course_history.json` - Course registration history

### 4. Management Command
- `core/management/commands/seed_data.py` - Loads fixtures automatically

### 5. Deployment Configuration
- `render.yaml` - Automated deployment configuration (updated to remove database service)

## Next Steps

1. **Deploy Now:**
   - Follow Step 1 to set up external PostgreSQL database (Supabase recommended)
   - Follow Step 2 & 3 to update render.yaml and deploy to Render
   - Set `DATABASE_URL` environment variable in Render dashboard
   - Your current development data will be automatically loaded

2. **Test Everything:**
   - Login with your existing accounts
   - Verify all timetables are present
   - Test admin functionality

3. **Future Updates:**
   - Make changes in development
   - Export fixtures
   - Commit and push
   - Render handles the rest automatically

## Benefits of This Approach

✅ **No More Data Loss**: PostgreSQL persists across deployments
✅ **Synchronized Data**: Development fixtures automatically load to production  
✅ **Easy Updates**: Simple git push updates production data
✅ **Rollback Safety**: Database changes are versioned with your code
✅ **Cost Effective**: Uses free tier PostgreSQL hosting (Supabase, ElephantSQL, etc.)
✅ **Flexible**: Can switch database providers easily by changing DATABASE_URL
✅ **Secure**: Database credentials stored as environment variables, not in code

## Troubleshooting

### Connection Issues
- **"Connection refused"**: Check that your database host allows connections from Render's IP addresses
- **"Authentication failed"**: Verify your database password is correct in the DATABASE_URL
- **"Database does not exist"**: Ensure the database name in your connection string is correct

### Neon Specific
- Use the **pooler connection** (not direct) for better performance with serverless
- Connection string format: `postgresql://user:password@host/database?sslmode=require`
- Remove `channel_binding=require` parameter if present (not needed for Django)
- Your connection string: `postgresql://neondb_owner:npg_Pm6pbMRzU5gA@ep-divine-tree-ahu5dja4-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require`
- Neon projects may pause after inactivity - check dashboard if connection fails

### Supabase Specific
- Make sure to replace `[YOUR-PASSWORD]` in the connection string with your actual password
- Check Supabase dashboard → Settings → Database for the correct connection string
- Ensure your Supabase project is not paused (free tier projects pause after inactivity)

### ElephantSQL Specific
- Free tier has a 20MB limit - monitor your database size
- Connection string format: `postgresql://user:password@host:port/database`

### General Tips
- Always test your DATABASE_URL locally before deploying:
  ```bash
  export DATABASE_URL="your-connection-string"
  python manage.py migrate
  ```
- Keep your database password secure - never commit it to git
- Consider using connection pooling for better performance (Supabase includes this automatically)
