"""Run with python -m src.services.command_lab_cli --command 'ssh pi@raspberrypi.local'."""
import argparse
import json
from src.services.command_lab_service import CommandLabError, CommandLabService


def main():
    parser = argparse.ArgumentParser(description="명령어 실험실: 분석·재조합 전용, 명령 실행 없음")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--command")
    group.add_argument("--template-id")
    group.add_argument("--audit", action="store_true")
    parser.add_argument("--values", default="{}", help="part ID → 입력값 JSON")
    parser.add_argument("--product-id")
    args = parser.parse_args()
    try:
        service = CommandLabService()
        result = (service.audit() if args.audit else service.analyze(args.command) if args.command
                  else service.compose(args.template_id, json.loads(args.values), product_id=args.product_id)
                  if args.template_id else service.list_templates())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.audit and result["errors"]:
            raise SystemExit(1)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    main()
