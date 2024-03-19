from rich import inspect

# From: https://stackoverflow.com/questions/66503901/undo-redo-implementation-using-stack

# Usage: push, pop, undo, redo

class Node:
	def __init__(self, data=None):
		self.data = data
		self.next = None
		self.prev = None

	def __str__(self):
		return f"Node({self.data})"


class Stack:
	def __init__(self):
		self.pointer = None
		self.beginning = None

	def push(self, x):
		# Make a new node to be pushed onto stack
		if not isinstance(x, Node):
			x = Node(x)

		if self.is_empty():
			# If stack is empty (points to None), point to the new single node (no next or prev)
			self.pointer = x
			self.beginning = x
		else:
			# stack not empty.
			x.next = self.pointer  # New node's next points to current: x->current
			self.pointer.prev = x  # current's prev points to new node: x<->current
			self.pointer = x  # pointer->x<->older (was "current"; x is now the new current)

	def pop(self):
		if self.is_empty():
			print(f'Stack Underflow')
		else:
			self.pointer = self.pointer.next

	def is_empty(self):
		return self.pointer is None

	def __str__(self):
		string = ''
		current = self.pointer
		while current:
			string += f'{current.data}->'
			current = current.next
		if string:
			print(f'Stack Pointer = {self.pointer.data}')
			return f'[{string[:-2]}]'
		return '[]'

	def undo(self):
		x = self.pointer
		self.pop()  # moves pointer to next (older) which will be None if reached end
		if x is None:
			return False
		else:
			return(x.data)

	def redo(self):
		if self.pointer:
			x = self.pointer.prev
		else:
			print('redo: no pointer, so no prev')
			#return False  # Wrong!
			if self.beginning:
				self.push(self.beginning)
				return(self.beginning.data)
			else:
				return False
		if x is None:
			print('redo: pointer.prev is None')
			return False
		else:
			self.push(x)
			return(x.data)

if __name__ == "__main__":
	stack = Stack()

	stack.push(1)
	stack.push(2)
	stack.push(3)
	stack.push(4)
	stack.push(5)

	print("stack is:")
	print(stack)
	print()

	print(stack.undo())

	print("after undo:")
	print(stack)
	print()
	inspect(stack.pointer)

	print(stack.redo())

	print("after redo:")
	print(stack)
