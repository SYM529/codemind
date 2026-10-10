"""Dialect translation unit tests for the MySQL wrapper (no database needed)."""
from database import MySQLConn


def test_insert_or_replace_with_into():
    sql = "INSERT OR REPLACE INTO evaluations(a,b) VALUES(?,?)"
    assert MySQLConn._translate(sql) == "REPLACE INTO evaluations(a,b) VALUES(%s,%s)"


def test_insert_or_replace_without_into():
    sql = "INSERT OR REPLACE evaluations(a) VALUES(?)"
    assert MySQLConn._translate(sql) == "REPLACE INTO evaluations(a) VALUES(%s)"


def test_insert_or_ignore_with_into():
    sql = "INSERT OR IGNORE INTO users(a) VALUES(?)"
    assert MySQLConn._translate(sql) == "INSERT IGNORE INTO users(a) VALUES(%s)"


def test_plain_insert_untouched():
    sql = "INSERT INTO feedback(a) VALUES(?)"
    assert MySQLConn._translate(sql) == "INSERT INTO feedback(a) VALUES(%s)"


def test_placeholder_conversion():
    assert MySQLConn._translate("SELECT * FROM t WHERE a=? AND b=?") == "SELECT * FROM t WHERE a=%s AND b=%s"
