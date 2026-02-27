// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title DebtToken
 * @notice Generic reusable ERC-20 debt token for Ping-Masters.
 *
 *         Deploy TWICE:
 *           DebtToken("Ping-Masters USD", "pmUSD")  ->  stablecoin for USD borrowers
 *           DebtToken("Ping-Masters INR", "pmINR")  ->  stablecoin for INR borrowers
 *
 *         Only the LendingEngine (the "minter") can mint or burn tokens.
 */
contract DebtToken {

    // ─── ERC-20 METADATA ─────────────────────────────────────────────────────

    string  public name;
    string  public symbol;
    uint8   public constant decimals = 18;

    // ─── STATE ───────────────────────────────────────────────────────────────

    uint256 public totalSupply;
    mapping(address => uint256)                     public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    address public minter;  // LendingEngine — sole mint/burn authority
    address public owner;   // Deployer      — can set minter once

    // ─── EVENTS ──────────────────────────────────────────────────────────────

    event Transfer(address indexed from,   address indexed to,      uint256 value);
    event Approval(address indexed owner_, address indexed spender, uint256 value);
    event MinterSet(address indexed minter);

    // ─── ERRORS ──────────────────────────────────────────────────────────────

    error Unauthorized();
    error InsufficientBalance();
    error InsufficientAllowance();
    error ZeroAddress();
    error MinterAlreadySet();

    // ─── CONSTRUCTOR ─────────────────────────────────────────────────────────

    /// @param name_    e.g. "Ping-Masters USD"  or  "Ping-Masters INR"
    /// @param symbol_  e.g. "pmUSD"             or  "pmINR"
    constructor(string memory name_, string memory symbol_) {
        name   = name_;
        symbol = symbol_;
        owner  = msg.sender;
    }

    // ─── ADMIN ───────────────────────────────────────────────────────────────

    /// @notice Set LendingEngine as the sole minter. Can only be called once.
    function setMinter(address _minter) external {
        if (msg.sender != owner)   revert Unauthorized();
        if (minter != address(0))  revert MinterAlreadySet();
        if (_minter == address(0)) revert ZeroAddress();
        minter = _minter;
        emit MinterSet(_minter);
    }

    // ─── MINT / BURN (LendingEngine only) ────────────────────────────────────

    function mint(address to, uint256 amount) external {
        if (msg.sender != minter) revert Unauthorized();
        if (to == address(0))     revert ZeroAddress();
        totalSupply   += amount;
        balanceOf[to] += amount;
        emit Transfer(address(0), to, amount);
    }

    function burn(address from, uint256 amount) external {
        if (msg.sender != minter)      revert Unauthorized();
        if (balanceOf[from] < amount)  revert InsufficientBalance();
        balanceOf[from] -= amount;
        totalSupply     -= amount;
        emit Transfer(from, address(0), amount);
    }

    // ─── ERC-20 STANDARD ─────────────────────────────────────────────────────

    function transfer(address to, uint256 amount) external returns (bool) {
        if (to == address(0))               revert ZeroAddress();
        if (balanceOf[msg.sender] < amount) revert InsufficientBalance();
        balanceOf[msg.sender] -= amount;
        balanceOf[to]         += amount;
        emit Transfer(msg.sender, to, amount);
        return true;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        if (spender == address(0)) revert ZeroAddress();
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transferFrom(
        address from,
        address to,
        uint256 amount
    ) external returns (bool) {
        if (to == address(0))          revert ZeroAddress();
        if (balanceOf[from] < amount)  revert InsufficientBalance();
        uint256 allowed = allowance[from][msg.sender];
        if (allowed != type(uint256).max) {
            if (allowed < amount) revert InsufficientAllowance();
            allowance[from][msg.sender] = allowed - amount;
        }
        balanceOf[from] -= amount;
        balanceOf[to]   += amount;
        emit Transfer(from, to, amount);
        return true;
    }
}
