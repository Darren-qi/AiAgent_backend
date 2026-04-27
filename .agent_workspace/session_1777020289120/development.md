project_create("python_adder")
file_write(path="calculator.py", content="""#!/usr/bin/env python3
\"\"\"Simple Python Addition Calculator\"\"\"

def main():
    \"\"\"Main calculator loop\"\"\"
    print("=" * 40)
    print("     欢迎使用加法计算器")
    print("=" * 40)
    print("输入两个数字，我将计算它们的和。")
    print("输入 'q' 退出程序。")
    print()

    while True:
        try:
            # 获取第一个数字
            first_input = input("请输入第一个数字: ")
            if first_input.lower() == 'q':
                print("感谢使用，再见！")
                break

            first_num = float(first_input)

            # 获取第二个数字
            second_input = input("请输入第二个数字: ")
            if second_input.lower() == 'q':
                print("感谢使用，再见！")
                break

            second_num = float(second_input)

            # 计算并显示结果
            result = first_num + second_num
            print(f"{first_num} + {second_num} = {result}")
            print("-" * 40)

        except ValueError:
            print("错误：请输入有效的数字（整数或小数）！")
            print("-" * 40)
        except KeyboardInterrupt:
            print("\\n程序被用户中断。")
            break

if __name__ == "__main__":
    main()
""")

STAGE_DONE: development

【工具执行结果】
✅ 创建项目 'python_adder'
📄 创建文件 'calculator.py'