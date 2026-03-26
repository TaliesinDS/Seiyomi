import tkinter as tk
from tkinter import messagebox, scrolledtext, filedialog
import requests
import pandas as pd
import json
import threading
import time
import os
from datetime import datetime, timedelta
from collections import defaultdict


class MangaDexExtractor:
    def __init__(self):
        self.access_token = None
        self.refresh_token = None
        self.client_id = None
        self.client_secret = None
        self.token_expires_at = None
        self.save_path = None

        # Create main window
        self.root = tk.Tk()
        self.root.title("MangaDex Data Extractor")
        self.root.geometry("800x700")

        self.setup_ui()

    def setup_ui(self):
        # Login form
        login_frame = tk.Frame(self.root)
        login_frame.pack(pady=10)

        tk.Label(login_frame, text="mangadex Credentials", font=("Arial", 14, "bold")).pack(pady=5)

        # Client ID with paste button
        client_id_frame = tk.Frame(login_frame)
        client_id_frame.pack(pady=2)
        tk.Label(client_id_frame, text="Client ID:").pack()
        entry_frame = tk.Frame(client_id_frame)
        entry_frame.pack()
        self.client_id_entry = tk.Entry(entry_frame, width=45)
        self.client_id_entry.pack(side=tk.LEFT)
        tk.Button(entry_frame, text="Paste", command=lambda: self.paste_to_entry(self.client_id_entry)).pack(
            side=tk.LEFT, padx=(5, 0))

        # Client Secret with paste button
        client_secret_frame = tk.Frame(login_frame)
        client_secret_frame.pack(pady=2)
        tk.Label(client_secret_frame, text="Client Secret:").pack()
        entry_frame = tk.Frame(client_secret_frame)
        entry_frame.pack()
        self.client_secret_entry = tk.Entry(entry_frame, width=45, show="*")
        self.client_secret_entry.pack(side=tk.LEFT)
        tk.Button(entry_frame, text="Paste", command=lambda: self.paste_to_entry(self.client_secret_entry)).pack(
            side=tk.LEFT, padx=(5, 0))

        # Username with paste button
        username_frame = tk.Frame(login_frame)
        username_frame.pack(pady=2)
        tk.Label(username_frame, text="Username:").pack()
        entry_frame = tk.Frame(username_frame)
        entry_frame.pack()
        self.username_entry = tk.Entry(entry_frame, width=45)
        self.username_entry.pack(side=tk.LEFT)
        tk.Button(entry_frame, text="Paste", command=lambda: self.paste_to_entry(self.username_entry)).pack(
            side=tk.LEFT, padx=(5, 0))

        # Password with paste button
        password_frame = tk.Frame(login_frame)
        password_frame.pack(pady=2)
        tk.Label(password_frame, text="Password:").pack()
        entry_frame = tk.Frame(password_frame)
        entry_frame.pack()
        self.password_entry = tk.Entry(entry_frame, width=45, show="*")
        self.password_entry.pack(side=tk.LEFT)
        tk.Button(entry_frame, text="Paste", command=lambda: self.paste_to_entry(self.password_entry)).pack(
            side=tk.LEFT, padx=(5, 0))

        # File save location section
        save_frame = tk.Frame(self.root)
        save_frame.pack(pady=10)

        tk.Label(save_frame, text="Save Location", font=("Arial", 12, "bold")).pack()

        path_frame = tk.Frame(save_frame)
        path_frame.pack(pady=5)

        self.save_path_var = tk.StringVar()
        self.save_path_var.set(os.getcwd())  # Default to current directory

        tk.Label(path_frame, text="Excel files will be saved to:").pack()
        path_display_frame = tk.Frame(path_frame)
        path_display_frame.pack()

        self.path_label = tk.Label(path_display_frame, textvariable=self.save_path_var,
                                   relief="sunken", width=60, anchor="w")
        self.path_label.pack(side=tk.LEFT, padx=(0, 5))

        tk.Button(path_display_frame, text="Browse", command=self.choose_save_location).pack(side=tk.LEFT)

        # Buttons section
        button_section = tk.Frame(self.root)
        button_section.pack(pady=10)

        # Main extraction buttons
        main_button_frame = tk.LabelFrame(button_section, text="Main Extractions", font=("Arial", 10, "bold"))
        main_button_frame.pack(fill="x", pady=5)

        main_buttons_row = tk.Frame(main_button_frame)
        main_buttons_row.pack(pady=5)

        self.all_status_button = tk.Button(main_buttons_row, text="Extract All Library Status",
                                           command=self.start_status_extraction, bg="blue", fg="white", width=20)
        self.all_status_button.pack(side=tk.LEFT, padx=5)

        tk.Button(main_buttons_row, text="Clear Log", command=self.clear_log, width=10).pack(side=tk.LEFT, padx=5)

        # Individual status buttons
        status_button_frame = tk.LabelFrame(button_section, text="Individual Status Extractions",
                                            font=("Arial", 10, "bold"))
        status_button_frame.pack(fill="x", pady=5)

        # First row of status buttons
        status_row1 = tk.Frame(status_button_frame)
        status_row1.pack(pady=2)

        self.reading_button = tk.Button(status_row1, text="Extract Reading",
                                        command=lambda: self.start_individual_status_extraction("reading"),
                                        bg="orange", fg="white", width=15)
        self.reading_button.pack(side=tk.LEFT, padx=2)

        self.completed_button = tk.Button(status_row1, text="Extract Completed",
                                          command=lambda: self.start_individual_status_extraction("completed"),
                                          bg="purple", fg="white", width=15)
        self.completed_button.pack(side=tk.LEFT, padx=2)

        self.on_hold_button = tk.Button(status_row1, text="Extract On-Hold",
                                        command=lambda: self.start_individual_status_extraction("on_hold"),
                                        bg="yellow", fg="black", width=15)
        self.on_hold_button.pack(side=tk.LEFT, padx=2)

        # Second row of status buttons
        status_row2 = tk.Frame(status_button_frame)
        status_row2.pack(pady=2)

        self.dropped_button = tk.Button(status_row2, text="Extract Dropped",
                                        command=lambda: self.start_individual_status_extraction("dropped"),
                                        bg="red", fg="white", width=15)
        self.dropped_button.pack(side=tk.LEFT, padx=2)

        self.plan_to_read_button = tk.Button(status_row2, text="Extract Plan to Read",
                                             command=lambda: self.start_individual_status_extraction("plan_to_read"),
                                             bg="cyan", fg="black", width=15)
        self.plan_to_read_button.pack(side=tk.LEFT, padx=2)

        self.re_reading_button = tk.Button(status_row2, text="Extract Re-reading",
                                           command=lambda: self.start_individual_status_extraction("re_reading"),
                                           bg="magenta", fg="white", width=15)
        self.re_reading_button.pack(side=tk.LEFT, padx=2)

        # Store all buttons for easy enabling/disabling
        self.all_buttons = [
            self.all_status_button, self.reading_button,
            self.completed_button, self.on_hold_button, self.dropped_button,
            self.plan_to_read_button, self.re_reading_button
        ]

        # Output text area
        tk.Label(self.root, text="Progress Log:", font=("Arial", 12, "bold")).pack(pady=(20, 5))
        self.text_widget = scrolledtext.ScrolledText(self.root, height=12, state="disabled")
        self.text_widget.pack(fill="both", expand=True, padx=10, pady=5)

    def choose_save_location(self):
        """Let user choose where to save the Excel file"""
        folder_path = filedialog.askdirectory(
            title="Choose folder to save Excel files",
            initialdir=self.save_path_var.get()
        )
        if folder_path:
            self.save_path_var.set(folder_path)
            self.print_to_gui(f"✓ Save location set to: {folder_path}")

    def paste_to_entry(self, entry_widget):
        """Paste clipboard content to the specified entry widget"""
        try:
            clipboard_content = self.root.clipboard_get()
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, clipboard_content)
            self.print_to_gui(f"✓ Pasted content to {entry_widget.winfo_name()} field")
        except tk.TclError:
            messagebox.showwarning("Paste Error", "No content in clipboard or clipboard is empty")
        except Exception as e:
            messagebox.showerror("Paste Error", f"Error pasting from clipboard: {str(e)}")

    def print_to_gui(self, *args, sep=" ", end="\n"):
        """Display text in the GUI text widget similar to print function"""
        text = sep.join(map(str, args)) + end
        print(text.strip())  # Also print to console
        self.text_widget.config(state="normal")
        self.text_widget.insert("end", f"[{datetime.now().strftime('%H:%M:%S')}] {text}")
        self.text_widget.see("end")
        self.text_widget.config(state="disabled")
        self.root.update()

    def clear_log(self):
        self.text_widget.config(state="normal")
        self.text_widget.delete(1.0, "end")
        self.text_widget.config(state="disabled")

    def start_status_extraction(self):
        """Start the all status extraction process in a separate thread"""
        self.disable_buttons()
        thread = threading.Thread(target=self.extract_status_data)
        thread.daemon = True
        thread.start()

    def start_individual_status_extraction(self, status):
        """Start individual status extraction process in a separate thread"""
        self.disable_buttons()
        thread = threading.Thread(target=lambda: self.extract_individual_status_data(status))
        thread.daemon = True
        thread.start()

    def disable_buttons(self):
        """Disable all extraction buttons during processing"""
        for button in self.all_buttons:
            button.config(state="disabled")

        # Update button texts to show processing
        self.all_status_button.config(text="Processing...")
        self.reading_button.config(text="Processing...")
        self.completed_button.config(text="Processing...")
        self.on_hold_button.config(text="Processing...")
        self.dropped_button.config(text="Processing...")
        self.plan_to_read_button.config(text="Processing...")
        self.re_reading_button.config(text="Processing...")

    def enable_buttons(self):
        """Re-enable all extraction buttons after processing"""
        for button in self.all_buttons:
            button.config(state="normal")

        # Restore original button texts
        self.all_status_button.config(text="Extract All Library Status")
        self.reading_button.config(text="Extract Reading")
        self.completed_button.config(text="Extract Completed")
        self.on_hold_button.config(text="Extract On-Hold")
        self.dropped_button.config(text="Extract Dropped")
        self.plan_to_read_button.config(text="Extract Plan to Read")
        self.re_reading_button.config(text="Extract Re-reading")

    def authenticate(self):
        """Authenticate with mangadex API using personal client credentials"""
        self.print_to_gui("Starting authentication process...")

        # Get credentials from form
        self.client_id = self.client_id_entry.get().strip()
        self.client_secret = self.client_secret_entry.get().strip()
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()

        if not all([self.client_id, self.client_secret, username, password]):
            self.print_to_gui("ERROR: All fields are required!")
            return False

        # Prepare authentication data exactly as in the API documentation
        creds = {
            "grant_type": "password",
            "username": username,
            "password": password,
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }

        try:
            self.print_to_gui("Sending authentication request...")
            r = requests.post(
                "https://auth.mangadex.org/realms/mangadex/protocol/openid-connect/token",
                data=creds
            )

            if r.status_code == 200:
                r_json = r.json()
                self.access_token = r_json["access_token"]
                self.refresh_token = r_json["refresh_token"]
                # Set token expiration to 14 minutes from now (expires at 15 minutes)
                self.token_expires_at = datetime.now() + timedelta(minutes=14)
                self.print_to_gui("✓ Authentication successful!")
                self.print_to_gui(f"✓ Token will be refreshed at: {self.token_expires_at.strftime('%H:%M:%S')}")
                return True
            else:
                self.print_to_gui(f"✗ Authentication failed: {r.status_code} - {r.text}")
                return False

        except Exception as e:
            self.print_to_gui(f"✗ Authentication error: {str(e)}")
            return False

    def refresh_access_token(self):
        """Refresh the access token using the refresh token"""
        self.print_to_gui("🔄 Refreshing access token...")

        # Use exact format from API documentation
        creds = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }

        try:
            r = requests.post(
                "https://auth.mangadex.org/realms/mangadex/protocol/openid-connect/token",
                data=creds
            )

            if r.status_code == 200:
                r_json = r.json()
                self.access_token = r_json["access_token"]
                # Update refresh token if provided
                if "refresh_token" in r_json:
                    self.refresh_token = r_json["refresh_token"]
                # Reset token expiration to 14 minutes from now
                self.token_expires_at = datetime.now() + timedelta(minutes=14)
                self.print_to_gui("✓ Access token refreshed successfully!")
                self.print_to_gui(f"✓ Next refresh scheduled for: {self.token_expires_at.strftime('%H:%M:%S')}")
                return True
            else:
                self.print_to_gui(f"✗ Token refresh failed: {r.status_code} - {r.text}")
                return False

        except Exception as e:
            self.print_to_gui(f"✗ Token refresh error: {str(e)}")
            return False

    def check_and_refresh_token(self):
        """Check if token needs refreshing and refresh if necessary"""
        if datetime.now() >= self.token_expires_at:
            self.print_to_gui("⏰ Token expired, refreshing...")
            return self.refresh_access_token()
        return True

    def make_authenticated_request(self, url, **kwargs):
        """Make an authenticated request with automatic token refresh"""
        # Check if token needs refreshing
        if not self.check_and_refresh_token():
            raise Exception("Failed to refresh token")

        headers = kwargs.get('headers', {})
        headers["Authorization"] = f"Bearer {self.access_token}"
        kwargs['headers'] = headers

        return requests.get(url, **kwargs)

    def fetch_manga_statuses(self):
        """Fetch manga IDs for all statuses from the API"""
        self.print_to_gui("Fetching manga statuses for all categories...")
        manga_status_ids = defaultdict(list)

        try:
            # Check token expiration before request
            if not self.check_and_refresh_token():
                self.print_to_gui("✗ Failed to refresh token, stopping extraction")
                return manga_status_ids

            response = self.make_authenticated_request("https://api.mangadex.org/manga/status")

            if response.status_code == 200:
                data = response.json()
                statuses_dict = data.get('statuses', {})

                # Group manga IDs by status
                for manga_id, status in statuses_dict.items():
                    manga_status_ids[status].append(manga_id)

                # Print summary
                for status, ids in manga_status_ids.items():
                    self.print_to_gui(f"✓ Retrieved {len(ids)} manga IDs for status '{status}'")

            else:
                self.print_to_gui(f"✗ Failed to fetch manga statuses: {response.status_code} - {response.text}")

        except Exception as e:
            self.print_to_gui(f"✗ Error fetching manga statuses: {str(e)}")

        return manga_status_ids

    def fetch_manga_details(self, manga_ids):
        """Fetch detailed manga info for a list of manga IDs"""
        self.print_to_gui(f"Fetching detailed manga info for {len(manga_ids)} manga...")
        manga_details = []

        for i, manga_id in enumerate(manga_ids, 1):
            try:
                # Check token expiration periodically
                if i % 50 == 0 and not self.check_and_refresh_token():
                    self.print_to_gui("✗ Failed to refresh token, stopping detail fetch")
                    break

                response = self.make_authenticated_request(f"https://api.mangadex.org/manga/{manga_id}")

                if response.status_code == 200:
                    data = response.json().get('data', {})
                    manga_details.append(data)
                    if i % 50 == 0:
                        self.print_to_gui(f"Fetched {i}/{len(manga_ids)} manga details...")
                else:
                    self.print_to_gui(f"✗ Failed to fetch details for manga ID {manga_id}: {response.status_code}")

            except Exception as e:
                self.print_to_gui(f"✗ Error fetching details for manga ID {manga_id}: {str(e)}")

            time.sleep(0.1)  # To avoid rate limiting

        self.print_to_gui(f"✓ Completed fetching manga details for {len(manga_details)} manga")
        return manga_details

    def process_and_export_status_manga(self, manga_status_ids):
        """Process manga details per status and export to separate Excel files"""
        for status, ids in manga_status_ids.items():
            self.print_to_gui(f"Processing status '{status}' with {len(ids)} manga...")
            if not ids:
                self.print_to_gui(f"No manga IDs found for status '{status}', skipping export.")
                continue

            # Fetch detailed manga info
            manga_details = self.fetch_manga_details(ids)

            if not manga_details:
                self.print_to_gui(f"✗ No manga details retrieved for status '{status}', skipping export.")
                continue

            # Flatten data similar to fetch_followed_manga
            flattened_data = self.flatten_nested_data(manga_details)

            if not flattened_data:
                self.print_to_gui(f"✗ No flattened data for status '{status}', skipping export.")
                continue

            # Export to Excel with filename including status
            filename = self.export_to_excel_with_status(flattened_data, status)

            if filename:
                self.print_to_gui(f"✓ Exported {len(flattened_data)} manga for status '{status}' to {filename}")
            else:
                self.print_to_gui(f"✗ Failed to export manga for status '{status}'")

    def process_and_export_individual_status(self, status, manga_ids):
        """Process manga details for a single status and export to Excel file"""
        self.print_to_gui(f"Processing status '{status}' with {len(manga_ids)} manga...")

        if not manga_ids:
            self.print_to_gui(f"No manga IDs found for status '{status}', extraction aborted.")
            return False

        # Fetch detailed manga info
        manga_details = self.fetch_manga_details(manga_ids)

        if not manga_details:
            self.print_to_gui(f"✗ No manga details retrieved for status '{status}', extraction aborted.")
            return False

        # Flatten data similar to fetch_followed_manga
        flattened_data = self.flatten_nested_data(manga_details)

        if not flattened_data:
            self.print_to_gui(f"✗ No flattened data for status '{status}', extraction aborted.")
            return False

        # Export to Excel with filename including status
        filename = self.export_to_excel_with_status(flattened_data, status)

        if filename:
            self.print_to_gui(f"✓ Exported {len(flattened_data)} manga for status '{status}' to {filename}")
            return True
        else:
            self.print_to_gui(f"✗ Failed to export manga for status '{status}'")
            return False

    def export_to_excel_with_status(self, data, status):
        """Export flattened data to Excel file with status in filename"""
        try:
            self.print_to_gui(f"Creating Excel file for status '{status}'...")
            df = pd.DataFrame(data)

            # Use the existing export_to_excel logic but modify filename
            # Define desired column order - base columns first, then dynamic ones
            base_columns = ["type", "id"]
            title_columns = sorted([col for col in df.columns if col.startswith("title")])
            description_columns = sorted([col for col in df.columns if col.startswith("description")])
            link_columns = []
            for col in df.columns:
                if col not in base_columns and not col.startswith(
                        ("title", "description", "tags", "author", "artist")) and col not in ["publicationDemographic",
                                                                                              "status", "year",
                                                                                              "lastVolume",
                                                                                              "lastChapter"]:
                    link_columns.append(col)
            link_columns = sorted(link_columns)
            other_base_columns = ["publicationDemographic", "status", "year", "lastVolume", "lastChapter"]
            relationship_columns = sorted([col for col in df.columns if col.startswith(("author", "artist"))])
            tag_columns = sorted([col for col in df.columns if col.startswith("tags")])
            ordered_columns = (base_columns + title_columns + description_columns +
                               link_columns + other_base_columns + relationship_columns + tag_columns)
            final_columns = [col for col in ordered_columns if col in df.columns]
            df = df[final_columns]

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"mangadex_{status}_series_{timestamp}.xlsx"
            save_directory = self.save_path_var.get()
            full_path = os.path.join(save_directory, filename)
            df.to_excel(full_path, index=False, engine='openpyxl')

            return full_path
        except Exception as e:
            self.print_to_gui(f"✗ Error exporting to Excel for status '{status}': {str(e)}")
            return None

    def get_correct_mangaupdates_url(self, url):
        """Get the correct MangaUpdates URL by resolving redirects for old format URLs"""
        # If url is already in the correct format, return as is
        if url.startswith("https://www.mangaupdates.com/series/") and "id=" not in url:
            return url

        # If url contains id=, visit the url and get the redirected url
        if "id=" in url:
            try:
                self.print_to_gui(f"🔗 Resolving MangaUpdates URL: {url}")
                response = requests.get(url, allow_redirects=True, timeout=10)
                if response.status_code == 200:
                    final_url = response.url
                    # Remove any trailing parts after last /
                    if final_url.endswith("/"):
                        final_url = final_url[:-1]
                    # Remove any path after last / except the last segment
                    parts = final_url.split("/")
                    if len(parts) > 5:
                        # Keep only up to series id
                        final_url = "/".join(parts[:5])
                    self.print_to_gui(f"✓ Resolved to: {final_url}")
                    return final_url
                else:
                    self.print_to_gui(f"⚠️ Failed to resolve URL (status {response.status_code}), using original")
                    return url
            except Exception as e:
                self.print_to_gui(f"⚠️ Error resolving URL: {str(e)}, using original")
                return url

        # Otherwise, return as is
        return url

    def create_link_url(self, link_type, link_value):
        """Convert link data to proper URLs based on link type with MangaUpdates URL resolution"""
        # Remove any prefix like "series/" from the value
        clean_value = link_value.replace("series/", "") if isinstance(link_value, str) else str(link_value)

        # Handle MangaUpdates specially with URL resolution
        if link_type == 'mu':
            # First create the URL as normal
            initial_url = f"https://www.mangaupdates.com/series/{clean_value}"

            # Check if it looks like an old-style ID (numeric) that needs resolution
            if clean_value.isdigit():
                # This is likely an old-style ID, construct the old URL format and resolve it
                old_url = f"https://www.mangaupdates.com/series.html?id={clean_value}"
                return self.get_correct_mangaupdates_url(old_url)
            else:
                # This is already in new format or might need resolution, check it
                return self.get_correct_mangaupdates_url(initial_url)

        # Handle other link types as before
        link_mappings = {
            'al': f"https://anilist.co/manga/{clean_value}",
            'kt': f"https://kitsu.app/manga/{clean_value}",
            'ap': f"https://www.anime-planet.com/manga/{clean_value}",
            'bw': f"https://bookwalker.jp/series/{clean_value}",
            'mal': f"https://myanimelist.net/manga/{clean_value}",
            'amz': str(link_value),  # Already a URL
            'raw': str(link_value),  # Already a URL
            'ebj': str(link_value),  # Already a URL
            'cdj': str(link_value)  # Already a URL
        }

        return link_mappings.get(link_type, str(link_value))

    def get_link_column_name(self, link_type):
        """Get proper column name for link type"""
        name_mappings = {
            'al': 'anilist',
            'kt': 'kitsu',
            'mu': 'mangaupdates',
            'ap': 'animeplanet',
            'bw': 'bookwalker',
            'mal': 'myanimelist',
            'amz': 'amazon',
            'raw': 'raw',
            'ebj': 'ebookjapan',
            'cdj': 'cdjapan'
        }

        return name_mappings.get(link_type, link_type)

    def flatten_nested_data(self, data_list):
        """Convert nested JSON data to flat structure for Excel export with proper URL formatting and null checking"""
        self.print_to_gui("Processing and flattening manga data...")

        flattened_data = []

        for i, manga in enumerate(data_list, 1):
            try:
                # Progress update every 50 items
                if i % 50 == 0:
                    self.print_to_gui(f"Processing manga {i}/{len(data_list)}...")

                attributes = manga.get("attributes", {}) or {}  # Handle None attributes
                flat_record = {
                    "type": manga.get("type", ""),
                    "id": f"https://mangadex.org/title/{manga.get('id', '')}"  # Convert ID to URL
                }

                # Handle titles with null checking
                titles = attributes.get("title") or {}
                if isinstance(titles, dict):
                    for j, (key, value) in enumerate(titles.items(), 1):
                        if value:  # Only add non-empty values
                            flat_record[f"title{j}"] = value

                # Handle descriptions with null checking
                descriptions = attributes.get("description") or {}
                if isinstance(descriptions, dict):
                    for j, (key, value) in enumerate(descriptions.items(), 1):
                        if value:  # Only add non-empty values
                            flat_record[f"description{j}"] = value

                # Handle links with null checking
                links = attributes.get("links") or {}
                if isinstance(links, dict):
                    link_counts = defaultdict(int)  # Track counts for each link type

                    for link_type, link_value in links.items():
                        if link_value:  # Only process non-empty link values
                            column_name = self.get_link_column_name(link_type)
                            link_counts[column_name] += 1

                            # Create column name with count if needed
                            if link_counts[column_name] == 1:
                                col_name = column_name
                            else:
                                col_name = f"{column_name}{link_counts[column_name]}"

                            # Convert to URL (with MangaUpdates resolution for 'mu' type)
                            url = self.create_link_url(link_type, link_value)
                            flat_record[col_name] = url

                # Simple fields with null checking
                flat_record["publicationDemographic"] = attributes.get("publicationDemographic", "")
                flat_record["status"] = attributes.get("status", "")
                flat_record["year"] = attributes.get("year", "")
                flat_record["lastVolume"] = attributes.get("lastVolume", "")
                flat_record["lastChapter"] = attributes.get("lastChapter", "")

                # Handle tags with null checking
                tags = attributes.get("tags") or []
                if isinstance(tags, list):
                    for j, tag in enumerate(tags, 1):
                        if tag and isinstance(tag, dict):
                            tag_attributes = tag.get("attributes") or {}
                            tag_name = tag_attributes.get("name") or {}

                            if isinstance(tag_name, dict):
                                # Get first available tag name
                                tag_text = next((value for value in tag_name.values() if value), "")
                                if tag_text:
                                    flat_record[f"tags{j}"] = tag_text

                # Handle relationships with null checking
                relationships = manga.get("relationships") or []
                if isinstance(relationships, list):
                    relationship_counts = defaultdict(int)  # Track counts for each relationship type

                    for rel in relationships:
                        if rel and isinstance(rel, dict):
                            rel_type = rel.get('type', '')
                            rel_id = rel.get('id', '')

                            # Skip cover_art relationships
                            if rel_type == 'cover_art':
                                continue

                            # Map author and artist to same URL format
                            if rel_type in ['author', 'artist'] and rel_id:
                                url = f"https://mangadex.org/author/{rel_id}"
                                column_name = rel_type

                                relationship_counts[column_name] += 1

                                # Create column name with count if needed
                                if relationship_counts[column_name] == 1:
                                    col_name = column_name
                                else:
                                    col_name = f"{column_name}{relationship_counts[column_name]}"

                                flat_record[col_name] = url

                flattened_data.append(flat_record)

            except Exception as e:
                self.print_to_gui(f"✗ Error processing manga {manga.get('id', 'unknown')}: {str(e)}")
                # Still add basic record even if some processing fails
                try:
                    basic_record = {
                        "type": manga.get("type", ""),
                        "id": f"https://mangadex.org/title/{manga.get('id', '')}"
                    }
                    flattened_data.append(basic_record)
                except:
                    pass  # Skip if even basic processing fails
                continue

        self.print_to_gui(f"✓ Successfully processed {len(flattened_data)} manga records")
        return flattened_data

    def extract_status_data(self):
        """Main extraction process for all manga reading statuses"""
        try:
            # Step 1: Authenticate
            if not self.authenticate():
                return

            # Step 2: Fetch manga statuses
            manga_status_ids = self.fetch_manga_statuses()
            if not manga_status_ids:
                self.print_to_gui("✗ No manga status data retrieved. Extraction aborted.")
                return

            # Step 3: Process and export each status
            self.process_and_export_status_manga(manga_status_ids)

            # Count total files created
            total_files = sum(1 for status, ids in manga_status_ids.items() if ids)
            messagebox.showinfo("Success",
                                f"All library status extraction completed!\n{total_files} Excel files created for different reading statuses.")

        except Exception as e:
            self.print_to_gui(f"✗ Unexpected error: {str(e)}")
            messagebox.showerror("Error", f"An unexpected error occurred: {str(e)}")

        finally:
            self.enable_buttons()

    def extract_individual_status_data(self, target_status):
        """Main extraction process for a single manga reading status"""
        try:
            # Step 1: Authenticate
            if not self.authenticate():
                return

            # Step 2: Fetch manga statuses
            manga_status_ids = self.fetch_manga_statuses()
            if not manga_status_ids:
                self.print_to_gui("✗ No manga status data retrieved. Extraction aborted.")
                return

            # Step 3: Check if target status exists
            if target_status not in manga_status_ids:
                self.print_to_gui(f"✗ No manga found for status '{target_status}'. Extraction aborted.")
                messagebox.showwarning("No Data", f"No manga found for status '{target_status}'.")
                return

            # Step 4: Process and export the specific status
            manga_ids = manga_status_ids[target_status]
            success = self.process_and_export_individual_status(target_status, manga_ids)

            if success:
                messagebox.showinfo("Success",
                                    f"Individual status extraction completed!\nExtracted {len(manga_ids)} manga for status '{target_status}'.")
            else:
                messagebox.showerror("Error", f"Failed to extract manga for status '{target_status}'")

        except Exception as e:
            self.print_to_gui(f"✗ Unexpected error: {str(e)}")
            messagebox.showerror("Error", f"An unexpected error occurred: {str(e)}")

        finally:
            self.enable_buttons()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    # Required packages
    required_packages = ["requests", "pandas", "openpyxl"]

    try:
        import requests
        import pandas
        import openpyxl
    except ImportError as e:
        print(f"Missing required package. Install with: pip install {' '.join(required_packages)}")
        exit(1)

    app = MangaDexExtractor()
    app.run()
