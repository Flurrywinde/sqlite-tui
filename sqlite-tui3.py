#!/usr/bin/env python

# To test while using, setup four terminal windows:
#   * textual console -x EVENT  # console that shows print's and other debugging info
#   * textual run --dev sqlite-tui2a.py  # the actual program in dev mode (so it uses the console)
#   * watch -d "sqlite3 ~/test.db 'select * from places;'"  # make sure the right changes go to right place in the db
#   * watch -d "tail /tmp/sqlite-tui2-errors.log"  # watch for sqlite errors

import os
import sys
import sqlite3
import time
import random
from itertools import cycle
import pyperclip
import re

from rich import inspect
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable
from textual.widgets import Static
from textual.widgets import Footer
from textual.widgets import TextArea
from textual.widgets import MarkdownViewer
from textual import events
from rich.console import Console
from textual.screen import Screen

import undostack

help_text = """
# sqlite-tui2a.py

## Features
- Undo/redo
- Search
- Edit cell contents
- Toggle boolean cell
- Vim-like movement (with count)
- Yank to clipboard
	- Paste in edit-cell mode with ctrl-shift-v
- Status bar

## Keybindings
### Movement
Arrow keys or   Move cursor
h,j,k,l

## Versions
sqlite-tui.py - doesn't use textual, proof-of-concept of filling a rich table with sqlite data
sqlite-tui2.py - first attempt at a textual table with sqlite data
sqlite-tui2a.py - getting really functional now (undo stack, search, more movements, etc), but modalscreen problems
sqlite-tui3.py - replace modalscreen with modes, put sqlite stuff into class, reverse and wrap search
"""

#dbfname = 'bdsmlr.db'
#dbtable = 'blogs'

dbfname = 'test.db'  # located at ~/ just for testing sqlite-tui. Del when done.
dbtable = 'places'

class HelpScreen(Screen):
	BINDINGS = [("escape", "switch_mode('table')", "Exit Help"),]

	#def _on_key(self, event: events.Key) -> None:
	#	app.pop_screen()

	def compose(self) -> ComposeResult:
		#yield Static(" Windows ", id="title")
		#yield Static(help_text)
		yield MarkdownViewer(help_text)
		#yield Static("Press any key to continue [blink]_[/]", id="any-key")

class TextAreaSearch(TextArea):
	"""A subclass of TextArea to be used for search bar input."""

	def _on_key(self, event: events.Key) -> None:
		if event.character == "(":
			# delme. Old (fun) example of closing ('s
			self.insert("()")
			self.move_cursor_relative(columns=-1)
			event.prevent_default()
		elif event.key == "enter":
			self.search()
		elif event.key == "escape":
			self.display = False

	def search(self):
		table = app.query_one(DataTable)
		self.display = False
		cur_row = table.cursor_coordinate.row
		cur_col = table.cursor_coordinate.column
		cur_col += 1  # don't search current cell. Start search from one ahead
		lastrow = table.row_count - 1
		lastcol = len(table.columns) - 1
		print(f'lr: {lastrow}, lc: {lastcol}')
		if cur_col > lastcol:
			cur_col = 0
			cur_row += 1
		if cur_row > lastrow:
			# searched from last col in last row. This is equivalent to no search at all
			return
		result = None
		for row in range(cur_row, lastrow):  # TODO: wrap on/off, reverse. Currently on searches from current position to end. Also TODO: not "stall" with massive amounts of data
			print(f'r: {row}')
			for col in range(cur_col, lastcol):
				print(f'c: {col} ({self.headers[col]})')
				cell = table.get_cell_at((row, col))
				result = re.search(rf'^.*{self.text.strip()}.*$', cell)  # seems a CR gets added after first search, so hitting 'n' made it search for the CR too and come up empty
				if col >= 0:
					print(f'searching for {self.text} in {cell}, {result}')
				else:
					#print(cell)
					pass
				if result:
					table.move_cursor(row=row, column=col)
					break
			if result:
				break
		table.focus()

class TextAreaInput(TextArea):
	"""A subclass of TextArea to be used like an advanced Input for cell updating."""

	def _on_key(self, event: events.Key) -> None:
		print(event)  # Key(key='enter', character='\r', name='enter', is_printable=False, aliases=['enter', 'ctrl+m'])
		#table = self.query_one(DataTable)  # no nodes match, I think cuz self is the textarea
		#table = app.query_one(DataTable)  # works, but don't need
		if event.character == "(":
			# delme. Old (fun) example of closing ('s
			self.insert("()")
			self.move_cursor_relative(columns=-1)
			event.prevent_default()
		elif event.key == "enter":
			app.on_input_submitted()
		elif event.key == "escape":
			self.display = False
		elif event.key == "down":
			app.on_input_submitted()
			#app.action_movecur(1, 0)
		elif event.key == "up":
			app.on_input_submitted()
			#app.action_movecur(-1, 0)
		#elif event.key == "left":  # can't trap these keys as user might use them to go left/right in the textarea. Duh!
		#	app.on_input_submitted()
		#	#app.action_movecur(0, -1)
		#elif event.key == "right":
		#	app.on_input_submitted()
		#	#app.action_movecur(0, 1)  # don't need these as it will already happen; I guess the event percolates


class TableScreen(Screen):
	#count: str  # Doesn't work. Says "AttributeError: 'TableApp' object has no attribute 'count'
	count = ''
	status = ''
	pki = None  # primary key index (i.e. column #). Prolly a better way to do this now that I set the rowkey in add_row to the rowid, but pki is used in conjunction with pkname to find the row in the db table
	cursors = cycle(["cell", "column", "row"])
	undos = undostack.Stack()

	CSS_PATH = "layers.tcss"

	# Third way to capture keystrokes besides BINDINGS and self.key_X()'s
	def _on_key(self, event: events.Key) -> None:
		app.clear_notifications()
		print(event)
		if event.key in ['g', 'G', 'circumflex_accent', 'dollar_sign', '0', 'ctrl+f', 'ctrl+b']:
			self.jumpcur(event.key)
		elif event.key =='y':
			self.yank()
		elif event.key =='slash':
			self.searchbar()
		elif event.key =='i':
			statusbar = self.query_one('#statusbar')
			statusbar.update('hi there!')
			if statusbar.display == False:
				statusbar.display = True
			else:
				statusbar.display = False
		elif event.key =='n':
			searchbar = self.query_one(TextAreaSearch)
			if searchbar.text != '':
				# Re-use text in invisible searchbar
				searchbar.search()

	# There are 3 ways to capture keystrokes in this class. This is only one of them.
	BINDINGS = [
		("4", "add_count('4')", "count + 4"),
		("5", "add_count('5')", "count + 5"),
		("6", "add_count('6')", "count + 6"),
		("7", "add_count('7')", "count + 7"),
		("8", "add_count('8')", "count + 8"),
		("9", "add_count('9')", "count + 9"),
		("0", "add_count('0')", "count + 0"),
		#("h", "movecur(column=-1)", "move cursor left"),  # why no work?
		("h", "movecur(0, -1)", "move cursor left"),
		("j", "movecur(1, 0)", "move cursor down"),
		("k", "movecur(-1, 0)", "move cursor up"),
		("l", "movecur(0, 1)", "move cursor right"),
		#("enter", "getvalue()", "call value if cursor==cell, row num, column label"),	# enter already bound
		("space", "togglecurcell", "if current cell is a (0,1) boolean, toggle it"),
		("u", "undo", "undo"),
		("ctrl+r", "redo", "redo"),
		("q", "quit", "quit app"),
	]

	def newdb(self, dbfile):
		def finddbfile(dirname):
			while dirname != '/':
				if os.path.isfile(f"{dirname}/{dbfname}"):
					return f"{dirname}/{dbfname}"
				else:
					# Keep going up the path
					dirname, discard = os.path.split(dirname)
			# Couldn't find it if got to here
			return False

		def create_connection(db_file):
			""" create a database connection to a SQLite database """
			if not os.path.isfile(db_file):
				debugtee('sqlerr', 'db file missing: {}'.format(db_file))
				return False

			try:
				conn = sqlite3.connect(db_file)
			except Error as e:
				print(e)
				return False
			# Why was this important?
			try:
				resultset = conn.execute(f"SELECT 1 FROM {dbtable} LIMIT 1;")
			except sqlite3.OperationalError as e:
				print(e)
				return False

			conn.execute(
				"PRAGMA journal_mode=WAL")  # I forget what this was for. It means can still read while db locked for writing
			conn.row_factory = sqlite3.Row  # So row['name'] works, i.e. not just integer indices but the column name
			return conn

		# database in current folder or above
		dbfile = finddbfile(os.getcwd())

		# open connection to dbfile
		if dbfile:
			conn = create_connection(dbfile)
			if not conn:
				sys.exit(1)
		else:
			print("No db file here or above.")
			sys.exit(1)
		return conn

	def opentable(self, dbtable):
		def get_primary_key():
			pk = self.conn.execute("select name from pragma_table_info(?) where pk=1", (dbtable,))  # {'cid': 8, 'name': 'pk', 'type': 'INTEGER', 'notnull': 0, 'dflt_value': None, 'pk': 1}
			pk = pk.fetchone()  # just use first primary key if more than one
			if pk:
				return pk['name']
			else:
				# no primary key, so go by rowid
				return 'rowid'

		fields = self.conn.execute("SELECT name FROM PRAGMA_TABLE_INFO(?);", (dbtable,))
		self.headers = [field[0] for field in fields.fetchall()]
		self.pkname = get_primary_key()
		cur = self.conn.cursor()
		# rows = cur.execute("SELECT * FROM ? WHERE name = ? LIMIT 3;", (dbtable, 'gothicmon',))  # why can't table be a ?
		if self.pkname == 'rowid':
			# table has no primary key, so append rowid to the end
			self.rows = cur.execute(f"SELECT *, rowid FROM {dbtable};")
		# self.headers.append('rowid')  # removed to try to use this as the DataTable "key"
		else:
			# normal case. Table has a primary key, so no need for rowid
			self.rows = cur.execute(f"SELECT * FROM {dbtable};")
		# Iterate fields to set pki (primary key index) and determine which columns are assumed boolean
		self.bools = []
		i = 0
		for field in self.headers:
			# Set pki to primary key index
			if field == self.pkname:
				# Set pki to column# of primary key
				self.pki = i
			i += 1
			# Find out if column in boolean (assume it is if has only 0 and 1 values, nothing else)
			minmax = self.conn.execute(f"SELECT min({field}) as min, max({field}) as max FROM {dbtable};").fetchone()
			if minmax['min'] == '0' and minmax['max'] == '1':
				self.bools.append(field)

	# Construct ROWS for the Textual table
	# ROWS = [tuple(headers)]  # Init ROWS (first row is the header)  # doing different way now
	# for item in rows:
	#	rowtuple = tuple()
	#	for field in headers:
	#		rowtuple = (*rowtuple, str(item[field]),)
	#	ROWS.append(rowtuple)
	## Exit if no rows (TODO: make this ok and add ability to insert new rows)
	# if len(ROWS) == 0:
	#	print(f'Empty table: {dbtable}')
	#	sys.exit()

	def compose(self) -> ComposeResult:
		#msgcontainer = Center()
		#msgcontainer.opacity = 0  # error. has no setter, so do in css file. Later: didn't work there either. Whole thing black.
		#with msgcontainer:  # Intention is to overlay box in middle of screen, but this only kinda works (needs css on Center). Might work with more css?
		#	yield Static("No message yet", id="box1")
		#yield Static("No message yet", id="box1")
		#yield Input(placeholder="hi!", id="updatecell")
		yield TextAreaInput(id="updatecell")
		yield DataTable()
		yield TextAreaSearch(id='searchbar')
		yield Static(id='statusbar')

	def on_mount(self) -> None:
		# Open default database
		self.conn = self.newdb(dbfname)
		# Open default table
		self.opentable(dbtable)
		# Setup table
		table = self.query_one(DataTable)
		table.cursor_type = next(self.cursors)
		table.zebra_stripes = True
		#table.add_columns(*ROWS[0])
		#table.add_rows(ROWS[1:])  # Start at 1 since 0 is the header
		table.add_columns(*self.headers)
		for row in self.rows.fetchall():
			r = tuple(v for k,v in dict(row).items() if k != 'rowid')
			rk = table.add_row(*r, key=row[self.pkname])
			#print(f'{rk}, {rk.value}, {int(rk)}')
		updatecell = self.query_one(TextAreaInput)
		updatecell.theme = 'github_light'  # {'dracula', 'vscode_dark', 'monokai', 'github_light', 'css'}  # Only good ones: monokai, github_light
		table.focus()

	def searchbar(self):
		searchbar = self.query_one('#searchbar')
		searchbar.display = True
		searchbar.focus()
		searchbar.clear()

	def yank(self):
		table = self.query_one(DataTable)
		cur_row = table.cursor_coordinate.row
		cur_col = table.cursor_coordinate.column
		pyperclip.copy(table.get_cell_at((cur_row, cur_col,)))

	# Not used yet. For now, hit 'e' for edit and ctrl-shift-v to paste
	def put(self):
		spam = pyperclip.paste()

	def action_undo(self):
		query = self.undos.undo()
		print(f'{query}')
		if query:
			app.clear_notifications()
			self.changecell(query['sql'], query['pk'], query['changefrom'], query['changeto'], query['row'], query['col'], isnew=False)  # swapped changefrom and changeto
		else:
			self.notify('Already at oldest change')

	def action_redo(self):
		query = self.undos.redo()
		print(f'{query}')
		if query:
			app.clear_notifications()
			self.changecell(query['sql'], query['pk'], query['changeto'], query['changefrom'], query['row'], query['col'], isnew=False)
		else:
			self.notify('Already at newest change')

	def action_quit(self):
		self.conn.close()
		sys.exit()

	# Aborted attempt at hiding a column by setting width to 0. Doesn't work.
	def hide_column(self, col_label):
		table = self.query_one(DataTable)
		for k, v in table.columns.items():
			# inspect(v)
			# if v.label == 'id':  # doesn't work
			if v.label == Text(col_label):
				#print(v.width)
				v.auto_width = False
				v.content_width = 0
				# table.columns[k].width = 0  # seems completely equivalent to v
				# table.columns[k].content_width = 0
				v.width = 0
			#print(v)
		#else:
		#	print(f'label is not "id": {v.label}, t: {type(v.label)}')

	# Update both table cell and db
	def changecell(self, sql, pk, changeto, changefrom, row, col, isnew=True, update_width=False):
		table = self.query_one(DataTable)
		parms = (changeto, pk)
		try:
			cur = self.conn.execute(sql, parms)
		except sqlite3.OperationalError as e:
			with open('/tmp/sqlite-tui2-errors.log', 'a') as f:
				f.write(f'{e}\n')
				f.write(f'{sql}, {parms}')
			return False
		if cur.rowcount == 1:
			# success
			self.conn.commit()
			# sql update successful, so update table on screen too
			table.update_cell_at((row, col), changeto, update_width=update_width)
			if isnew:
				# Only push onto undos stack if new. undo/redo use changecell too and need to pass isnew=False
				self.undos.push({'sql': sql, 'pk': pk, 'changeto': changeto, 'changefrom': changefrom, 'row': row, 'col': col})
			return True
		elif cur.rowcount == 0:
			# failure
			self.notify("DB change unsuccessful")
		elif cur.rowcount < 0:
			# huh?
			self.notify("rowcount < 0???")
		else:
			# rowcount > 1 (not good!)
			self.notify('Updated more than 1 row???')
		# Only error cases get here, so rollback
		print(f'crc: {cur.rowcount}')
		self.conn.rollback()
		return False

	# Toggles current cell if it's "boolean"
	# Use with care, i.e. only on columns that really are boolean
	def action_togglecurcell(self):
		table = self.query_one(DataTable)
		cur_row = table.cursor_coordinate.row
		cur_col = table.cursor_coordinate.column
		col = self.headers[cur_col]
		if col not in self.bools:
			# No a boolean column, so do nothing, not even alert user
			return
		# Else, assume column is boolean
		text = table.get_cell_at((cur_row, cur_col,))
		if text == '0':
			changeto = '1'
		elif text == '1':
			changeto = '0'
		else:
			return  # do nothing, not even let user know this failed
		# Get the row's primary key value
		if self.pki:
			pk = table.get_cell_at((cur_row, self.pki,))
		else:
			pk = table.coordinate_to_cell_key((cur_row, cur_col,)).row_key.value
		#print(f'wehre pk={pk}, setting {col} to {changeto}')
		self.changecell(f'update {dbtable} set {col}=? where {self.pkname}=?', pk, changeto, text, cur_row, cur_col)

	# User is done editing a cell, so clear and hide textbox, show submitted message
	def on_input_submitted(self):  # function name same as when was event handler for Input; hopefully can just call it in TextAreaInput's key handler
		#updatecell = self.query_one(Input)
		updatecell = self.query_one(TextAreaInput)
		#changeto = updatecell.value
		changeto = updatecell.text
		print(f'ct: {changeto}')
		# updatecell.remove()  # this seems to be the culprit of below bug. Tried moving it after notify, but didn't help (but screen mess up didn't happen until move cursor)
		updatecell.display = False  # this confirms it. Hide it instead of remove it, and screen mess up bug doesn't happen
		table = self.query_one(DataTable)
		cur_row = table.cursor_coordinate.row
		cur_col = table.cursor_coordinate.column
		col = self.headers[cur_col]
		if self.pki:
			pk = table.get_cell_at((cur_row, self.pki,))
		else:
			pk = table.coordinate_to_cell_key((cur_row, cur_col,)).row_key.value
		changefrom = table.get_cell_at((cur_row, cur_col,))  # TODO: verify with actual db data here too?
		#print(f'update {dbtable} set {col}={changeto} where {self.pkname}={pk}')
		if self.changecell(f'update {dbtable} set {col}=? where {self.pkname}=?', pk, changeto, changefrom, cur_row, cur_col, update_width=True):
			self.notify('Success!')  # use simple built-in notify instead of showmsg/posize complexity

	# Currently just for testing. Append current cell to /tmp/v when user hits enter
	def on_data_table_cell_selected(self):
		table = self.query_one(DataTable)
		cur_row = table.cursor_coordinate.row
		cur_col = table.cursor_coordinate.column
		cell_contents = table.get_cell_at((cur_row, cur_col,))
		with open('/tmp/v', 'a') as f:
			f.write(f'{cell_contents}\n')

	def jumpcur(self, where):
		table = self.query_one(DataTable)
		row = table.cursor_coordinate.row
		col = table.cursor_coordinate.column
		vpwidth = table.container_viewport.width
		vpheight = table.container_viewport.height
		if where == 'g':
			row = 0
		elif where == 'G':
			row = table.row_count - 1
		elif where == 'circumflex_accent' or where == '0':
			col = 0
		elif where == 'dollar_sign':
			col = len(table.columns) - 1
			print(f'col: {len(table.columns) - 1}')
		elif where == 'ctrl+f':
			newrow = row + vpheight - 1  # -1 for maybe the scrollbar or cursor being on the row?
			if newrow > table.row_count - 1:
				row = table.row_count - 1
			else:
				row = newrow
		elif where == 'ctrl+b':
			newrow = row - vpheight + 1
			if newrow < 0:
				row = 0
			else:
				row = newrow
		table.move_cursor(row=row, column=col)
		self.count = ''

	# Move table's cursor. Parms should be 0,1,-1 to convey which direction to move. (Will be multiplied by the vim-like count.)
	def action_movecur(self, row, column) -> None:
		table = self.query_one(DataTable)

		cur_row = table.cursor_coordinate.row
		cur_col = table.cursor_coordinate.column
		#print(f'r: {cur_row}, c: {cur_col}')
		if self.count:
			count = int(self.count)
		else:
			count = 1
		#print(f'table.move_cursor(row={cur_row}+{count}*{row}={cur_row+count*row}, column={cur_col}+{count}*{column}={cur_col + count*column}, count: {count}, {row}/{column} animate=True)')
		target_row = cur_row + count*row
		target_col = cur_col + count*column
		numrows = table.row_count
		numcols = len(table.columns)
		# Wrap horizontal movement but not vertical.
		# TODO: doesn't work quite right, but good enough for now
		if target_col > numcols - 1:  # -1 cuz zero-based
			linesdown = int(target_col / numcols)  # Example: Table has 3 cols: 0 1 2. Currently on col 2. Count is 5, so target_row is 7. linesdown = 7 / 3 = 2. Should wind up on col 1. 7 % 3 = 1, so worked!
			target_col = target_col % numcols
			target_row += linesdown
		elif target_col < 0:
			linesdown = int(target_col / numcols) - 1  # negative linesdown is lines up
			target_col = numcols - ((target_col * -1) % numcols)  # *-1 of a known neg number is same as absolute value
			target_row += linesdown
		table.move_cursor(row=target_row, column=target_col)
		self.count = ''

	# Vim-like count
	def action_add_count(self, num: str) -> None:
		self.count += num

	# Change cursor type between cell, column, and row
	def key_c(self):
		table = self.query_one(DataTable)
		table.cursor_type = next(self.cursors)

	def key_e(self):
		def getyoffset(cols, table):
			# Misnomer: gets yoffset AND width for updatecell
			totwidth = 0
			curcol = 0
			for column in table.columns:
				colwidth = table.columns[column].get_render_width(table)  # table.columns[column].width is width of header it seems
				if curcol > cols:
					# Doing this here makes colwidth = width of current column, but totwidth is just the preceeding columns
					break
				totwidth += colwidth
				curcol += 1

			#for i in range(0, cols):
				#msgbox.update(f'{i}: {list(table.columns)[i].get_render_width(table)}')
				#time.sleep(1)
			return colwidth, totwidth

		#updatecell = self.query_one(Input)
		#updatecell = TextAreaInput(id="updatecell")  # nope, can't make a new one each time, as removing it (after submit) causes screen mess up
		#self.mount(updatecell)
		#updatecell.is_scrollable = False  # has no setter
		updatecell = self.query_one(TextAreaInput)
		#nextone = False
		#themes = list(updatecell.available_themes)
		#for theme in themes:
		#	if nextone:
		#		updatecell.theme = theme
		#		break
		#	if theme == updatecell.theme:
		#		if theme == themes[-1]:
		#			updatecell.theme = themes[0]
		#			break
		#		else:
		#			nextone = True
		#print(updatecell.theme)
		#updatecell.clear()  # don't need since will put in current value
		updatecell.styles.scrollbar_size_horizontal = 0  # seems to work to hide scrollbars; content still scrolls like I want
		updatecell.styles.scrollbar_size_vertical = 0
		table = self.query_one(DataTable)
		cur_row = table.cursor_coordinate.row
		cur_col = table.cursor_coordinate.column
		w, yoffset = getyoffset(cur_col - 1, table)
		updatecell.offset = (yoffset - table.scroll_target_x, cur_row + 1 - table.scroll_target_y)  # assumes all row heights == 1; need +1 to get past header (so assumes header is also height == 1)
		#updatecell.styles.padding = (0, 1, 0, 1)  # top, right, bottom, left
		updatecell.styles.padding = (0, 0, 0, 1)  # got rid of right padding as if text filled whole thing, it scrolled left
		updatecell.styles.width = w
		updatecell.text = str(table.get_cell_at((cur_row, cur_col,)))
		updatecell.select_all()
		app.clear_notifications()
		updatecell.display = True  # 'block' or 'none'
		updatecell.focus()

	#def key_j(self):  # don't use key_j and key_k anymore. Use movecur
	#	table = self.query_one(DataTable)
	#	#x, y = table.coordinate_to_cell_key(table.cursor_coordinate)  # no good. Cell key is some internal id that stays same even if cell is moved
	#	cur_row = table.cursor_coordinate.row
	#	cur_col = table.cursor_coordinate.column
	#	if self.count:
	#		count = int(self.count)
	#	else:
	#		count = 1
	#	table.cursor_coordinate = (cur_row + count, cur_col)
	#	#table.cursor_down()  # doesn't exist, so why in docs? https://textual.textualize.io/widgets/data_table/#textual.widgets._data_table.DataTable.cursor_coordinate
	#	self.count = ''

	#def key_k(self):
	#	table = self.query_one(DataTable)
	#	cur_row = table.cursor_coordinate.row
	#	if self.count:
	#		count = int(self.count)
	#	else:
	#		count = 1
	#	table.move_cursor(row = cur_row - count, animate=True)
	#	self.count = ''

	def key_1(self):
		self.count += '1'

	def key_2(self):
		self.count += '2'

	def key_3(self):
		self.count += '3'

class TableApp(App):
	BINDINGS = [
		("question_mark", "switch_mode('help')", "Help"),
	]

	MODES = {
		'table': TableScreen,
		'help': HelpScreen
	}

	def on_mount(self) -> None:
		self.switch_mode("table")

app = TableApp()
if __name__ == "__main__":
	app.run()
