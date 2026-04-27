```
project_create("python_calculator")
```

```
file_write(path="calculator.py", content="\"\"\"\nSimple Addition Calculator\n\nA command-line calculator that takes two numbers and displays their sum.\n\"\"\"\n\n\ndef get_number(prompt: str) -> float:\n    \"\"\"Prompt the user for a number and return it as a float.\n\n    Args:\n        prompt: The input prompt string\n\n    Returns:\n        The number entered by the user\n\n    Raises:\n        ValueError: If the input cannot be converted to a number\n    \"\"\"\n    while True:\n        try:\n            user_input = input(prompt)\n            return float(user_input)\n        except ValueError:\n            print(\"Invalid input! Please enter a valid number.\")\n\n\ndef add_numbers(a: float, b: float) -> float:\n    \"\"\"Calculate the sum of two numbers.\n\n    Args:\n        a: First number\n        b: Second number\n\n    Returns:\n        The sum of a and b\n    \"\"\"\n    return a + b\n\n\ndef main() -> None:\n    \"\"\"Main entry point of the calculator program.\"\"\"\n    print(\"=\" * 40)\n    print(\"      Simple Addition Calculator\")\n    print(\"=\" * 40)\n\n    # Get two numbers from user\n    num1 = get_number(\"Enter the first number: \")\n    num2 = get_number(\"Enter the second number: \")\n\n    # Calculate and display result\n    result = add_numbers(num1, num2)\n\n    print(\"-\" * 40)\n    print(f\"Result: {num1} + {num2} = {result}\")\n    print(\"=\" * 40)\n\n\nif __name__ == \"__main__\":\n    main()\n")
```

STAGE_DONE: development

【工具执行结果】
✅ 创建项目 'python_calculator'
📄 创建文件 'calculator.py'