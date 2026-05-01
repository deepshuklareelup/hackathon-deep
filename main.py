"""
Rofy Reel Agent — CLI Entry Point

Usage:
  python main.py --product sample_product.json
  python main.py --product sample_product.json --image product.jpg
  python main.py --product sample_product.json --no-approve --output ./my_output
"""
import argparse
import json
import sys
from pathlib import Path

# Load env before anything else
import config  # noqa: F401 — triggers _load_env()

from agent.orchestrator import run
from models import ProductInput


def parse_args():
    parser = argparse.ArgumentParser(
        prog="rofy-reel-agent",
        description="AI agent that turns a product JSON into a short-form video reel",
    )
    parser.add_argument(
        "--product", "-p",
        required=True,
        help="Path to product JSON file (see sample_product.json for format)",
    )
    parser.add_argument(
        "--image", "-i",
        default=None,
        help="Path to product image (optional — used as visual context)",
    )
    parser.add_argument(
        "--output", "-o",
        default="./output",
        help="Output directory for generated files (default: ./output)",
    )
    parser.add_argument(
        "--no-approve",
        action="store_true",
        default=False,
        help="Skip human approval step and run fully automatically",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Load product JSON
    product_path = Path(args.product)
    if not product_path.exists():
        print(f"Error: Product file not found: {product_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(product_path) as f:
            product_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {product_path}: {e}", file=sys.stderr)
        sys.exit(1)

    # Validate image path if provided
    image_path = None
    if args.image:
        img = Path(args.image)
        if not img.exists():
            print(f"Warning: Image file not found: {img} — continuing without it")
        else:
            image_path = str(img)

    product = ProductInput.from_dict(product_data, image_path=image_path)

    # Run the pipeline
    job = run(
        product=product,
        output_dir=args.output,
        human_approval=not args.no_approve,
    )

    # Exit with error code if failed
    if job.status == "failed":
        print(f"\nPipeline failed: {job.error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
