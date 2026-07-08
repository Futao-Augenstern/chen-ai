"""
技能系统使用示例

演示如何使用技能系统和技能建议。
"""

from skills import SkillManager


def main():
    print("=" * 50)
    print("  技能系统使用示例")
    print("=" * 50)

    # 初始化技能管理器
    skill_mgr = SkillManager()

    # 列出所有技能分类
    print("\n技能分类:")
    categories = set(s.category for s in skill_mgr.list_skills())
    for cat in sorted(categories):
        count = sum(1 for s in skill_mgr.list_skills() if s.category == cat)
        print(f"  - {cat}: {count} 个技能")

    # 列出所有技能
    print("\n所有技能:")
    for skill in skill_mgr.list_skills():
        print(f"  [{skill.category}] {skill.name} - {skill.description}")

    # 技能建议
    test_inputs = [
        "帮我写一个 Python 脚本",
        "这个界面怎么设计比较好",
        "帮我优化一下 SQL 查询",
        "我想写一篇技术文章",
    ]

    print("\n技能建议示例:")
    for text in test_inputs:
        suggestion = skill_mgr.suggest_skill(text)
        if suggestion:
            print(f"  输入: \"{text}\" → 推荐: {suggestion.name}")
        else:
            print(f"  输入: \"{text}\" → 无匹配技能")

    # 获取某个技能的详情
    skill = skill_mgr.get_skill("代码助手")
    if skill:
        print(f"\n技能详情 - {skill.name}:")
        print(f"  描述: {skill.description}")
        print(f"  分类: {skill.category}")
        print(f"  关联工具: {', '.join(skill.tools)}")
        print(f"  使用次数: {skill.usage_count}")


if __name__ == "__main__":
    main()
