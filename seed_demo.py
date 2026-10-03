#!/usr/bin/env python3
"""Seed 8 fictional demo profiles for DateSwipe. Run once: python3 seed_demo.py
All profiles are fictional. Password for all: demo1234"""
import hashlib
import json
import os
import secrets
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from app import gen_referral_code  # noqa: E402  (needs DB ready; app.py inits on import)

DB = os.path.join(ROOT, "date_swipe.db")
DEMOS = [
    ("Ayesha", "female", "1998-03-14", "female",
     "Coffee first, deep conversations later. ☕",
     "photography, hiking, novels"),
    ("Daniyal", "male", "1995-07-22", "female",
     "Weekend chef, weekday engineer. Will fight you for the last slice. 🍕",
     "cooking, football, tech"),
    ("Sara", "female", "1997-11-02", "everyone",
     "Dog mom of two. Swipe right if you can handle the chaos. 🐶",
     "dogs, travel, yoga"),
    ("Bilal", "male", "1994-01-30", "female",
     "Gym at 6, biryani at 9. Balance is everything.",
     "fitness, food, movies"),
    ("Mahnoor", "female", "1999-05-19", "male",
     "Artist by day, overthinker by night. 🎨",
     "art, music, chai"),
    ("Usman", "male", "1996-09-08", "everyone",
     "Just a guy with a camera and too many travel plans. 📸",
     "travel, photography, gaming"),
    ("Hira", "female", "1995-12-25", "male",
     "Bookstore wanderer. Ask me about my top 5 novels.",
     "books, poetry, long walks"),
    ("Ahmed", "male", "1993-04-11", "female",
     "Startup life, dad jokes, and surprisingly good pancakes. 🥞",
     "startups, comedy, brunch"),
]


def main():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    added = 0
    for i, (name, gender, dob, looking, bio, interests) in enumerate(DEMOS):
        email = f"demo{i + 1}@dateswipe.local"
        if db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            print(f"skip {email} (exists)")
            continue
        salt = secrets.token_hex(16)
        pw = hashlib.pbkdf2_hmac("sha256", b"demo1234", salt.encode(), 200_000).hex()
        db.execute(
            """INSERT INTO users(email,pw_hash,salt,name,birthdate,gender,looking_for,
                                 bio,interests,created_ts,referral_code)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (email, pw, salt, name, dob, gender, looking, bio, interests,
             int(time.time()), gen_referral_code()),
        )
        added += 1
    db.commit()
    print(f"seeded {added} demo profiles (password: demo1234)")


if __name__ == "__main__":
    main()
